"""Appointments patients book through the Endod app, as this hospital sees them.

They arrive as ``appointment.requested`` events (already paid to Endod). An
in-person visit is confirmed at once; a video visit waits for a doctor to
approve it, which opens a video room. Every decision goes back to the patient
platform as an event: ``appointment.confirmed``, ``appointment.rejected``,
``appointment.cancelled`` (each of the last two refunds the patient there) and
``appointment.completed``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from pydantic import AwareDatetime, BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import eventbus, jitsi
from app.db import ensure_aware, session_scope, utcnow
from app.eventbus import PermanentEventError, RetryLater
from app.models import Booking, BookingStatus, Hospital, HospitalStatus, Service, StaffUser, VisitMode

logger = logging.getLogger("hospital.bookings")


def _reject_unknown(session: Session, payload: Dict[str, Any], reason: str) -> None:
    eventbus.emit(session, "appointment.rejected", {
        "appointment_id": payload.get("appointment_id"), "hospital_id": payload.get("hospital_id"),
        "reason": reason,
    })


class _Patient(BaseModel):
    dedan_id: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=160)
    phone: Optional[str] = Field(default=None, max_length=20)


class Requested(BaseModel):
    """``appointment.requested``, checked before anything is stored."""

    appointment_id: str = Field(min_length=1, max_length=64)
    hospital_id: str = Field(min_length=1, max_length=32)
    patient: _Patient
    visit_mode: str
    service: Optional[str] = Field(default=None, max_length=40)
    #: Must carry its offset: a bare clock time would be read in the wrong zone.
    scheduled_at: AwareDatetime
    duration_minutes: int = Field(default=30, ge=5, le=480)
    notes: Optional[str] = Field(default=None, max_length=2000)
    #: Santim, an integer (a birr amount sent as 150.0 is refused, not misread).
    price: int = Field(ge=0, strict=True)


class _Ref(BaseModel):
    appointment_id: str = Field(min_length=1, max_length=64)


def _parse(model, payload: Dict[str, Any]):
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise PermanentEventError(str(exc).splitlines()[0]) from exc


def on_requested(session: Session, payload: Dict[str, Any]) -> None:
    """A patient booked (and paid for) a visit here."""
    try:
        request = _parse(Requested, payload)
    except PermanentEventError:
        ids = (payload.get("appointment_id"), payload.get("hospital_id"))
        if all(isinstance(v, str) and 0 < len(v) <= 64 for v in ids):
            # The patient has paid: answer, so the platform refunds them,
            # rather than drop the request where no one sees it.
            _reject_unknown(session, payload, "The booking details could not be accepted.")
            return
        raise
    if session.scalar(select(Booking.id).where(Booking.external_id == request.appointment_id)) is not None:
        return  # already known (a redelivery under a new event id)
    hospital = session.get(Hospital, request.hospital_id)
    if hospital is None or hospital.status != HospitalStatus.APPROVED:
        _reject_unknown(session, payload, "This hospital is not taking bookings through Endod right now.")
        return
    mode = request.visit_mode
    if mode not in VisitMode.ALL or (mode == VisitMode.VIDEO and not hospital.video_enabled):
        _reject_unknown(session, payload, "This hospital does not offer this kind of visit right now.")
        return
    booking = Booking(
        hospital_id=hospital.id, external_id=request.appointment_id,
        patient_dedan_id=request.patient.dedan_id, patient_name=request.patient.name,
        patient_phone=request.patient.phone, visit_mode=mode,
        service=request.service if request.service in Service.ALL else None,
        # Stored in UTC: SQLite would otherwise drop the offset and keep the
        # wall-clock time, moving the visit by the offset (3 hours in Addis).
        scheduled_at=request.scheduled_at.astimezone(timezone.utc), duration_minutes=request.duration_minutes,
        notes=request.notes, price=request.price,
        status=BookingStatus.CONFIRMED if mode == VisitMode.IN_PERSON else BookingStatus.AWAITING_DOCTOR,
    )
    session.add(booking)
    session.flush()
    if booking.status == BookingStatus.CONFIRMED:
        eventbus.emit(session, "appointment.confirmed", _decision(booking))


def on_patient_cancelled(session: Session, payload: Dict[str, Any]) -> None:
    """The patient cancelled in the Endod app (and has been refunded there)."""
    ref = _parse(_Ref, payload)
    booking = session.scalar(select(Booking).where(Booking.external_id == ref.appointment_id).with_for_update())
    if booking is None:
        # The booking has not arrived yet (its event is being retried): try
        # again later rather than lose the cancellation.
        raise RetryLater(f"booking {ref.appointment_id} not received yet")
    if booking.status not in BookingStatus.OPEN:
        return
    booking.status = BookingStatus.CANCELLED
    booking.reason = "Cancelled by the patient."
    booking.decided_at = utcnow()


HANDLERS = {
    "appointment.requested": on_requested,
    "appointment.cancelled": on_patient_cancelled,
}


def _decision(booking: Booking, doctor_name: Optional[str] = None) -> Dict[str, Any]:
    return {
        "appointment_id": booking.external_id,
        "hospital_id": booking.hospital_id,
        "status": booking.status,
        "meeting_room": booking.meeting_room,
        "doctor_name": doctor_name,
        "reason": booking.reason,
    }


class BookingError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def approve_video(session: Session, booking: Booking, doctor: StaffUser, decided_by: str) -> None:
    if booking.visit_mode != VisitMode.VIDEO:
        raise BookingError("Only video visits need a doctor's approval.")
    if booking.status != BookingStatus.AWAITING_DOCTOR:
        raise BookingError("This visit is not waiting for approval.", 409)
    if ensure_aware(booking.scheduled_at) < utcnow():
        raise BookingError("This visit's time has passed; it can no longer be approved.", 409)
    booking.status = BookingStatus.CONFIRMED
    booking.doctor_id = doctor.id
    booking.meeting_room = jitsi.new_room()
    booking.decided_by, booking.decided_at = decided_by, utcnow()
    eventbus.emit(session, "appointment.confirmed", _decision(booking, doctor.full_name))


def reject(session: Session, booking: Booking, reason: str, decided_by: str) -> None:
    if booking.status != BookingStatus.AWAITING_DOCTOR:
        raise BookingError("Only a visit waiting for approval can be rejected; cancel a confirmed one.", 409)
    booking.status = BookingStatus.REJECTED
    booking.reason = reason
    booking.decided_by, booking.decided_at = decided_by, utcnow()
    eventbus.emit(session, "appointment.rejected", _decision(booking))


def cancel(session: Session, booking: Booking, reason: str, decided_by: str) -> None:
    if booking.status == BookingStatus.AWAITING_DOCTOR:
        # Declining a visit nobody approved yet is a rejection.
        reject(session, booking, reason, decided_by)
        return
    if booking.status not in BookingStatus.OPEN:
        raise BookingError("This visit is already closed.", 409)
    booking.status = BookingStatus.CANCELLED
    booking.reason = reason
    booking.decided_by, booking.decided_at = decided_by, utcnow()
    eventbus.emit(session, "appointment.cancelled", {**_decision(booking), "by": "hospital"})


def complete(session: Session, booking: Booking, decided_by: str) -> None:
    if booking.status != BookingStatus.CONFIRMED:
        raise BookingError("Only a confirmed visit can be completed.", 409)
    if ensure_aware(booking.scheduled_at) > utcnow():
        raise BookingError("A visit cannot be completed before it starts.", 409)
    booking.status = BookingStatus.COMPLETED
    booking.decided_by, booking.decided_at = decided_by, utcnow()
    eventbus.emit(session, "appointment.completed", _decision(booking))


#: A video visit nobody approved is declined this long after it was due to start.
APPROVAL_GRACE = timedelta(minutes=15)


def expire_unapproved() -> int:
    """Decline video visits whose time passed without a doctor's approval
    (the patient is refunded on the platform). Returns how many."""
    cutoff = utcnow() - APPROVAL_GRACE
    expired = 0
    with session_scope() as session:
        stale = session.scalars(select(Booking).where(
            Booking.status == BookingStatus.AWAITING_DOCTOR, Booking.scheduled_at < cutoff,
        ).with_for_update()).all()
        for booking in stale:
            booking.status = BookingStatus.REJECTED
            booking.reason = "No doctor approved this visit in time."
            booking.decided_at = utcnow()
            eventbus.emit(session, "appointment.rejected", _decision(booking))
            expired += 1
    return expired
