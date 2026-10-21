"""Doctors' queues: one per doctor per day (docs/history-events.md, section 4).

Every change to a queue first locks its ``queue_days`` row with a write (an
UPDATE), so changes to one queue happen one at a time on PostgreSQL and on
SQLite alike: two clicks on "call next" cannot call two patients, and two
check-ins cannot take the same ticket.

After each change, every open entry whose position or status changed is
announced with ``queue.updated``: always for an entry linked to Endod, and
for anyone with a phone when there is something to notify ("near" once when
the people ahead first reach the hospital's ``queue_notify_ahead``, "turn"
once when called).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

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


def call_next(session: Session, queue: QueueDay) -> QueueEntry:
    """Call the next waiting patient. Refused while someone is still called:
    the doctor finishes (or skips) them first, so a second click calls nobody."""
    current = entries(session, queue.id)
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
              and ahead <= near_at):
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
