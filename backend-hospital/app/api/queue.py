"""Doctors' queues (docs/history-events.md, section 4).

Reception and admins check patients in and see every doctor's queue; a
doctor sees and runs their own. A patient arrives by an Endod booking (which
links the hospital patient to Endod), as a registered patient, or as a
walk-in with a name and phone number.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import linking, queues, records
from app.auth import Staff, audit, require_roles
from app.db import session_scope
from app.models import (
    Booking, BookingStatus, Hospital, Patient, QueueDay, QueueEntry, QueueStatus, Role, StaffUser, VisitMode,
)
from app.validation import Name, OptionalPhone, OptionalText, normalize_dedan_id

router = APIRouter(prefix="/queue", tags=["queue"])

#: Who checks patients in and runs any doctor's queue.
QUEUE_DESK = (Role.ADMIN, Role.RECEPTION)
queue_staff = require_roles(*QUEUE_DESK, Role.DOCTOR)


class WalkIn(BaseModel):
    name: Name = Field(max_length=160)
    phone: OptionalPhone = None

    @model_validator(mode="after")
    def _phone(self):
        if not self.phone:
            raise ValueError("a walk-in needs a phone number (for the SMS when their turn comes)")
        return self


class CheckIn(BaseModel):
    doctor_id: OptionalText = Field(default=None, max_length=32)
    booking_id: OptionalText = Field(default=None, max_length=32)
    patient_id: OptionalText = Field(default=None, max_length=32)
    walk_in: Optional[WalkIn] = None

    @model_validator(mode="after")
    def _one_way(self):
        if self.walk_in is not None and (self.booking_id or self.patient_id):
            raise ValueError("a walk-in has no booking or patient record")
        if self.walk_in is None and not (self.booking_id or self.patient_id):
            raise ValueError("give a booking, a patient or a walk-in")
        return self


def queue_doctor(session, hospital_id: str, doctor_id: Optional[str]) -> StaffUser:
    doctor = session.scalar(select(StaffUser).where(
        StaffUser.id == doctor_id, StaffUser.hospital_id == hospital_id, StaffUser.role == Role.DOCTOR,
        StaffUser.active.is_(True))) if doctor_id else None
    if doctor is None:
        raise HTTPException(status_code=400, detail="Choose the doctor.")
    return doctor


def _doctor(session, staff: Staff, doctor_id: Optional[str]) -> StaffUser:
    return queue_doctor(session, staff.hospital_id, doctor_id)


def _own_queue_only(staff: Staff, doctor_id: str) -> None:
    if staff.role == Role.DOCTOR and doctor_id != staff.id:
        raise HTTPException(status_code=403, detail="A doctor runs only their own queue.")


def queue_payload(session, doctor: StaffUser, queue: Optional[QueueDay],
                   earlier: Optional[QueueDay] = None) -> Dict[str, Any]:
    """The doctor's queue for the day, with ``leftovers``: entries of the
    previous day still open (called first; cancelled by the worker later)."""
    all_entries = queues.entries(session, queue.id) if queue else []
    open_entries = [e for e in all_entries if e.status in QueueStatus.OPEN]
    left = [e for e in queues.entries(session, earlier.id) if e.status in QueueStatus.OPEN] if earlier else []
    leftovers = [queues.payload(e, left) | {"day": earlier.day.isoformat()} for e in left]
    current = [queues.payload(e, open_entries) for e in open_entries]
    return {
        "doctor": {"id": doctor.id, "full_name": doctor.full_name},
        "entries": [queues.payload(e, open_entries) for e in all_entries],
        "leftovers": leftovers,
        "waiting": sum(1 for e in left + open_entries if e.status == QueueStatus.WAITING),
        "called": next((e for e in leftovers + current if e["status"] == QueueStatus.CALLED), None),
    }


def board(session, hospital_id: str, day: Optional[date], doctor_id: Optional[str]) -> Dict[str, Any]:
    """Every active doctor's queue for the day (or one doctor's), with today's
    leftovers from yesterday. Shared by the portal and the integration API."""
    today = records.hospital_today(session, hospital_id)
    day = day or today
    query = select(StaffUser).where(StaffUser.hospital_id == hospital_id, StaffUser.role == Role.DOCTOR,
                                    StaffUser.active.is_(True))
    if doctor_id:
        query = query.where(StaffUser.id == doctor_id)
    doctors = list(session.scalars(query.order_by(StaffUser.full_name)))
    days = {q.doctor_id: q for q in session.scalars(select(QueueDay).where(
        QueueDay.hospital_id == hospital_id, QueueDay.day == day))}
    # Today's board also shows yesterday's leftovers (they are called first).
    earlier = {q.doctor_id: q for q in session.scalars(select(QueueDay).where(
        QueueDay.hospital_id == hospital_id, QueueDay.day == today - timedelta(days=1)))}         if day == today else {}
    hospital = session.get(Hospital, hospital_id)
    return {"day": day.isoformat(), "today": today.isoformat(), "notify_ahead": hospital.queue_notify_ahead,
            "queues": [queue_payload(session, d, days.get(d.id), earlier.get(d.id)) for d in doctors]}


@router.get("")
def list_queues(day: Optional[date] = Query(default=None), doctor_id: Optional[str] = Query(default=None),
                staff: Staff = Depends(queue_staff)) -> Dict[str, Any]:
    with session_scope(staff.hospital_id) as session:
        if staff.role == Role.DOCTOR:
            doctor_id = staff.id
        return board(session, staff.hospital_id, day, doctor_id)


def check_in_patient(session, hospital_id: str, body: CheckIn, actor_id: Optional[str],
                     audit_extra: Optional[Dict[str, Any]] = None) -> Tuple[StaffUser, QueueDay, QueueEntry]:
    """Check a patient in to a doctor's queue for today (by booking, patient or
    walk-in), announce it and audit it. Shared by the portal and the
    integration API. IntegrityError: the booking is already checked in."""
    today = records.hospital_today(session, hospital_id)
    booking: Optional[Booking] = None
    patient: Optional[Patient] = None
    if body.booking_id:
        booking = session.scalar(select(Booking).where(
            Booking.id == body.booking_id, Booking.hospital_id == hospital_id).with_for_update())
        if booking is None:
            raise HTTPException(status_code=404, detail="Booking not found.")
        if booking.status != BookingStatus.CONFIRMED or booking.visit_mode != VisitMode.IN_PERSON:
            raise HTTPException(status_code=409, detail="Only a confirmed in-person booking is checked in.")
    if body.patient_id:
        patient = session.scalar(select(Patient).where(
            Patient.id == body.patient_id, Patient.hospital_id == hospital_id).with_for_update())
        if patient is None:
            raise HTTPException(status_code=404, detail="Patient not found.")
    if booking is not None:
        dedan_id = _booking_dedan(booking)
        if patient is None and dedan_id:
            patient = linking.holder_of(session, hospital_id, dedan_id)
        if patient is not None and dedan_id:
            # The platform identified the patient when they booked: link
            # the hospital record without asking again.
            try:
                linking.link(session, patient, dedan_id, today)
            except linking.LinkError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
    doctor = queue_doctor(session, hospital_id, body.doctor_id or (booking.doctor_id if booking else None))
    queue = queues.lock_queue(session, hospital_id, doctor.id, today)
    if booking is not None:
        name, phone = booking.patient_name, booking.patient_phone
        dedan_id = _booking_dedan(booking)
    elif patient is not None:
        name, phone, dedan_id = patient.full_name, patient.phone, patient.dedan_id
    else:
        name, phone, dedan_id = body.walk_in.name, body.walk_in.phone, None
    if patient is not None:
        name, dedan_id = patient.full_name, patient.dedan_id or dedan_id
    try:
        entry = queues.check_in(session, queue, patient_name=name, phone=phone, dedan_id=dedan_id,
                                patient_id=patient.id if patient else None,
                                booking_id=booking.id if booking else None, staff_id=actor_id)
    except queues.QueueError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    queues.announce(session, queue, [entry.id])
    audit(session, hospital_id, actor_id, "queue_checked_in", "queue_entry", entry.id,
          {"doctor_id": doctor.id, "ticket": entry.ticket, "booking_id": entry.booking_id,
           "patient_id": entry.patient_id, **(audit_extra or {})})
    session.flush()
    return doctor, queue, entry


@router.post("/check-in", status_code=status.HTTP_201_CREATED)
def check_in(body: CheckIn, staff: Staff = Depends(require_roles(*QUEUE_DESK))) -> Dict[str, Any]:
    try:
        with session_scope(staff.hospital_id) as session:
            doctor, queue, entry = check_in_patient(session, staff.hospital_id, body, staff.id)
            return queue_payload(session, doctor, queue) | {"entry_id": entry.id, "ticket": entry.ticket}
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="This booking is already checked in.") from exc


def _booking_dedan(booking: Booking) -> Optional[str]:
    try:
        return normalize_dedan_id(booking.patient_dedan_id)
    except ValueError:
        return None


def call_next_patient(session, hospital_id: str, doctor_id: str, actor_id: Optional[str],
                      audit_extra: Optional[Dict[str, Any]] = None) -> Tuple[StaffUser, QueueDay, Optional[QueueDay]]:
    """Call the doctor's next waiting patient, announce it and audit it."""
    doctor = queue_doctor(session, hospital_id, doctor_id)
    today = records.hospital_today(session, hospital_id)
    # Patients still waiting from before midnight come first. Always the
    # earlier day's queue locked first, then today's (no lock-order deadlock).
    earlier = queues.lock_existing(session, hospital_id, doctor.id, today - timedelta(days=1))
    queue = queues.lock_queue(session, hospital_id, doctor.id, today)
    try:
        entry = queues.call_next(session, queue, earlier)
    except queues.QueueError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    queues.announce(session, earlier if earlier is not None and entry.queue_id == earlier.id else queue,
                    [entry.id])
    audit(session, hospital_id, actor_id, "queue_called", "queue_entry", entry.id,
          {"ticket": entry.ticket, **(audit_extra or {})})
    session.flush()
    return doctor, queue, earlier


@router.post("/{doctor_id}/call-next")
def call_next(doctor_id: str, staff: Staff = Depends(queue_staff)) -> Dict[str, Any]:
    _own_queue_only(staff, doctor_id)
    with session_scope(staff.hospital_id) as session:
        doctor, queue, earlier = call_next_patient(session, staff.hospital_id, doctor_id, staff.id)
        return queue_payload(session, doctor, queue, earlier)


ACTIONS = {"done": QueueStatus.DONE, "skip": QueueStatus.SKIPPED, "cancel": QueueStatus.CANCELLED}


def entry_with_queue(session, hospital_id: str, entry_id: str) -> Tuple[QueueEntry, QueueDay]:
    found = session.execute(select(QueueEntry, QueueDay).join(QueueDay, QueueDay.id == QueueEntry.queue_id)
                            .where(QueueEntry.id == entry_id, QueueEntry.hospital_id == hospital_id)).first()
    if found is None:
        raise HTTPException(status_code=404, detail="Queue entry not found.")
    return found[0], found[1]


def finish_entry(session, hospital_id: str, entry_id: str, action: str, actor_id: Optional[str],
                 audit_extra: Optional[Dict[str, Any]] = None) -> QueueDay:
    """Mark an entry done, skipped or cancelled (``action``: done, skip, cancel), announce and audit it."""
    _entry, day = entry_with_queue(session, hospital_id, entry_id)
    queue = queues.lock_queue(session, hospital_id, day.doctor_id, day.day)
    entry = session.scalar(select(QueueEntry).where(QueueEntry.id == entry_id)
                           .execution_options(populate_existing=True))
    try:
        queues.finish(entry, ACTIONS[action])
    except queues.QueueError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    queues.announce(session, queue, [entry.id])
    audit(session, hospital_id, actor_id, f"queue_{entry.status}", "queue_entry", entry.id,
          {"ticket": entry.ticket, **(audit_extra or {})})
    session.flush()
    return queue


@router.post("/entries/{entry_id}/{action}")
def finish(entry_id: str, action: str, staff: Staff = Depends(queue_staff)) -> Dict[str, Any]:
    if action not in ACTIONS:
        raise HTTPException(status_code=404, detail="Not found.")
    with session_scope(staff.hospital_id) as session:
        _entry, day = entry_with_queue(session, staff.hospital_id, entry_id)
        _own_queue_only(staff, day.doctor_id)
        queue = finish_entry(session, staff.hospital_id, entry_id, action, staff.id)
        return queue_payload(session, session.get(StaffUser, queue.doctor_id), queue)
