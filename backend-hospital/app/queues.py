"""Doctors' queues: one per doctor per day (docs/history-events.md, section 4).

Every change to a queue first locks its ``queue_days`` row with a write (an
UPDATE), so changes to one queue happen one at a time on PostgreSQL and on
SQLite alike: two clicks on "call next" cannot call two patients, and two
check-ins cannot take the same ticket.

After each change, every open entry whose position or status changed is
announced with ``queue.updated``: always for an entry linked to Endod, and
for anyone with a phone when there is something to notify:

* "near", once, when the people ahead *decrease* to the hospital's
  ``queue_notify_ahead`` or fewer after check-in. Never at check-in itself:
  an entry checked in with that few people ahead gets no "near", only "turn";
* "turn", once, when the entry is called.

Queues outlive midnight a little: "call next" takes waiting patients from
the previous hospital day first (oldest day, then ticket), and the worker
cancels entries still open :data:`STALE_AFTER` after their day ended
(announced as ``cancelled``, so the Endod app never shows a stale "waiting").
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app import eventbus
from app.db import new_id, utcnow
from app.models import Hospital, QueueDay, QueueEntry, QueueStatus, StaffUser
from app.records import iso


class QueueError(ValueError):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def _insert(session: Session):
    dialect = session.get_bind().dialect.name
    return (postgresql if dialect == "postgresql" else sqlite).insert(QueueDay)


def lock_queue(session: Session, hospital_id: str, doctor_id: str, day: date) -> QueueDay:
    """The doctor's queue for the day, created if needed, and locked for this
    transaction (the UPDATE holds the row lock until commit)."""
    session.execute(_insert(session).values(
        id=new_id(), hospital_id=hospital_id, doctor_id=doctor_id, day=day, last_ticket=0, changes=0,
    ).on_conflict_do_nothing(index_elements=["hospital_id", "doctor_id", "day"]))
    session.execute(update(QueueDay).where(
        QueueDay.hospital_id == hospital_id, QueueDay.doctor_id == doctor_id, QueueDay.day == day,
    ).values(changes=QueueDay.changes + 1))
    queue = session.scalar(select(QueueDay).where(
        QueueDay.hospital_id == hospital_id, QueueDay.doctor_id == doctor_id, QueueDay.day == day,
    ).with_for_update().execution_options(populate_existing=True))
    return queue


def entries(session: Session, queue_id: str) -> List[QueueEntry]:
    return list(session.scalars(select(QueueEntry).where(QueueEntry.queue_id == queue_id)
                                .order_by(QueueEntry.ticket)))


def ahead_of(open_entries: List[QueueEntry], entry: QueueEntry) -> int:
    """People still waiting before this entry (the one being seen is not counted)."""
    if entry.status != QueueStatus.WAITING:
        return 0
    return sum(1 for e in open_entries if e.status == QueueStatus.WAITING and e.ticket < entry.ticket)


def check_in(session: Session, queue: QueueDay, *, patient_name: str, phone: Optional[str],
             dedan_id: Optional[str], patient_id: Optional[str], booking_id: Optional[str],
             staff_id: Optional[str]) -> QueueEntry:
    if patient_id and session.scalar(select(QueueEntry.id).where(
            QueueEntry.queue_id == queue.id, QueueEntry.patient_id == patient_id,
            QueueEntry.status.in_(QueueStatus.OPEN))):
        raise QueueError("This patient is already in this queue.")
    queue.last_ticket += 1
    entry = QueueEntry(
        hospital_id=queue.hospital_id, queue_id=queue.id, ticket=queue.last_ticket,
        status=QueueStatus.WAITING, patient_id=patient_id, booking_id=booking_id, dedan_id=dedan_id,
        patient_name=patient_name, phone=phone, checked_in_by=staff_id,
    )
    session.add(entry)
    session.flush()
    return entry


def lock_existing(session: Session, hospital_id: str, doctor_id: str, day: date) -> Optional[QueueDay]:
    """Like :func:`lock_queue`, but None (and nothing created) when the doctor
    had no queue that day."""
    found = session.execute(update(QueueDay).where(
        QueueDay.hospital_id == hospital_id, QueueDay.doctor_id == doctor_id, QueueDay.day == day,
    ).values(changes=QueueDay.changes + 1))
    if not found.rowcount:
        return None
    return session.scalar(select(QueueDay).where(
        QueueDay.hospital_id == hospital_id, QueueDay.doctor_id == doctor_id, QueueDay.day == day,
    ).with_for_update().execution_options(populate_existing=True))


def call_next(session: Session, queue: QueueDay, earlier: Optional[QueueDay] = None) -> QueueEntry:
    """Call the next waiting patient: from ``earlier`` (the previous hospital
    day's queue, locked first) before ``queue``, then by ticket. Refused while
    someone is still called: the doctor finishes (or skips) them first, so a
    second click calls nobody."""
    current = (entries(session, earlier.id) if earlier is not None else []) + entries(session, queue.id)
    called = [e for e in current if e.status == QueueStatus.CALLED]
    if called:
        raise QueueError(f"Ticket {called[0].ticket} ({called[0].patient_name}) is still called. "
                         "Mark them done or skipped first.")
    waiting = [e for e in current if e.status == QueueStatus.WAITING]
    if not waiting:
        raise QueueError("Nobody is waiting.")
    entry = waiting[0]
    entry.status, entry.called_at = QueueStatus.CALLED, utcnow()
    return entry


#: An entry still waiting (or called) this long after its day ended is cancelled.
STALE_AFTER = timedelta(hours=12)


def day_ended(day: date, zone: ZoneInfo) -> datetime:
    """The moment ``day`` ended where the hospital is (its next midnight)."""
    return datetime.combine(day + timedelta(days=1), time.min, zone)


def cancel_stale(session: Session, now: Optional[datetime] = None) -> int:
    """Cancel entries still open :data:`STALE_AFTER` after their day ended, and
    announce them (``cancelled``). Returns how many were cancelled."""
    now = now or utcnow()
    # Even at UTC+14, a day plus STALE_AFTER ends no earlier than 22:00 UTC that
    # same date: later days cannot be stale yet (the exact check is below).
    stale = session.execute(
        select(QueueDay.id, QueueDay.day, Hospital.timezone).join(Hospital, Hospital.id == QueueDay.hospital_id)
        .where(QueueDay.day <= now.date(), QueueDay.id.in_(
            select(QueueEntry.queue_id).where(QueueEntry.status.in_(QueueStatus.OPEN))))).all()
    cancelled = 0
    for queue_id, day, zone in stale:
        if now < day_ended(day, ZoneInfo(zone)) + STALE_AFTER:
            continue
        queue = session.get(QueueDay, queue_id)
        queue = lock_queue(session, queue.hospital_id, queue.doctor_id, queue.day)
        changed = []
        for entry in entries(session, queue.id):
            if entry.status in QueueStatus.OPEN:
                entry.status, entry.finished_at = QueueStatus.CANCELLED, now
                changed.append(entry.id)
        if changed:
            announce(session, queue, changed)
            cancelled += len(changed)
    return cancelled


def finish(entry: QueueEntry, status: str) -> None:
    allowed = {
        QueueStatus.DONE: (QueueStatus.CALLED,),
        QueueStatus.SKIPPED: (QueueStatus.WAITING, QueueStatus.CALLED),
        QueueStatus.CANCELLED: (QueueStatus.WAITING, QueueStatus.CALLED),
    }[status]
    if entry.status not in allowed:
        if status == QueueStatus.DONE and entry.status == QueueStatus.WAITING:
            raise QueueError("Call this patient before marking them done.")
        raise QueueError(f"This ticket is already {entry.status}.")
    entry.status, entry.finished_at = status, utcnow()


def announce(session: Session, queue: QueueDay, changed: Optional[List[str]] = None) -> int:
    """Send ``queue.updated`` for each entry whose status or position changed
    (``changed``: entries whose status just changed). Returns how many were sent."""
    hospital = session.get(Hospital, queue.hospital_id)
    doctor = session.get(StaffUser, queue.doctor_id)
    near_at = hospital.queue_notify_ahead or 0
    all_entries = entries(session, queue.id)
    open_entries = [e for e in all_entries if e.status in QueueStatus.OPEN]
    changed_ids = set(changed or [])
    sent = 0
    for entry in all_entries:
        if entry.status not in QueueStatus.OPEN and entry.id not in changed_ids:
            continue
        ahead = ahead_of(open_entries, entry)
        notify = None
        if entry.status == QueueStatus.CALLED and not entry.turn_notified:
            notify = "turn"
            entry.turn_notified = True
        elif (entry.status == QueueStatus.WAITING and near_at > 0 and not entry.near_notified
              and entry.last_ahead > near_at >= ahead):
            # Only when the people ahead come down to the threshold after
            # check-in (last_ahead is -1 until then): someone checked in with
            # that few ahead already knows, and gets only "turn".
            notify = "near"
            entry.near_notified = True
        moved = entry.id in changed_ids or ahead != entry.last_ahead
        entry.last_ahead = ahead
        # Linked entries follow every move in the app; anyone with a phone gets the SMS.
        if not ((entry.dedan_id and (moved or notify)) or (notify and entry.phone)):
            continue
        entry.seq += 1
        eventbus.emit(session, "queue.updated", {
            "entry_id": entry.id, "hospital_id": hospital.id, "hospital_name": hospital.name,
            "doctor_name": doctor.full_name if doctor else None, "day": queue.day.isoformat(),
            "ticket": entry.ticket, "status": entry.status, "ahead": ahead, "dedan_id": entry.dedan_id,
            "phone": entry.phone, "patient_name": entry.patient_name, "notify": notify, "seq": entry.seq,
        })
        sent += 1
    return sent


def payload(entry: QueueEntry, open_entries: List[QueueEntry]) -> Dict[str, Any]:
    return {
        "id": entry.id, "ticket": entry.ticket, "status": entry.status,
        "ahead": ahead_of(open_entries, entry),
        "patient_name": entry.patient_name, "phone": entry.phone, "dedan_id": entry.dedan_id,
        "patient_id": entry.patient_id, "booking_id": entry.booking_id,
        "checked_in_at": iso(entry.checked_in_at),
        "called_at": iso(entry.called_at) if entry.called_at else None,
        "finished_at": iso(entry.finished_at) if entry.finished_at else None,
    }


def waiting_count(session: Session, queue_id: str) -> int:
    return session.scalar(select(func.count()).where(QueueEntry.queue_id == queue_id,
                                                     QueueEntry.status == QueueStatus.WAITING)) or 0
