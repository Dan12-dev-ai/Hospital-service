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
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import eventbus, jitsi
from app.db import ensure_aware, utcnow
from app.models import Booking, BookingStatus, Hospital, HospitalStatus, StaffUser, VisitMode

logger = logging.getLogger("hospital.bookings")


def _reject_unknown(session: Session, payload: Dict[str, Any], reason: str) -> None:
    eventbus.emit(session, "appointment.rejected", {
        "appointment_id": payload.get("appointment_id"), "hospital_id": payload.get("hospital_id"),
        "reason": reason,
    })


def on_requested(session: Session, payload: Dict[str, Any]) -> None:
    """A patient booked (and paid for) a visit here."""
    external_id = str(payload["appointment_id"])
    if session.scalar(select(Booking.id).where(Booking.external_id == external_id)) is not None:
        return  # already known (a redelivery under a new event id)
    hospital = session.get(Hospital, str(payload.get("hospital_id")))
    if hospital is None or hospital.status != HospitalStatus.APPROVED:
        _reject_unknown(session, payload, "This hospital is not taking bookings through Endod right now.")
        return
    mode = payload.get("visit_mode")
    if mode not in VisitMode.ALL or (mode == VisitMode.VIDEO and not hospital.video_enabled):
        _reject_unknown(session, payload, "This hospital does not offer this kind of visit right now.")
        return
    patient = payload.get("patient") or {}
    booking = Booking(
        hospital_id=hospital.id, external_id=external_id,
        patient_dedan_id=str(patient.get("dedan_id") or "")[:16],
        patient_name=str(patient.get("name") or "Endod patient")[:160],
        patient_phone=(patient.get("phone") or None),
        visit_mode=mode, service=payload.get("service"),
        scheduled_at=datetime.fromisoformat(payload["scheduled_at"]),
        duration_minutes=int(payload.get("duration_minutes") or 30),
        notes=payload.get("notes"), price=int(payload.get("price") or 0),
        status=BookingStatus.CONFIRMED if mode == VisitMode.IN_PERSON else BookingStatus.AWAITING_DOCTOR,
    )
    session.add(booking)
    session.flush()
    if booking.status == BookingStatus.CONFIRMED:
        eventbus.emit(session, "appointment.confirmed", _decision(booking))


def on_patient_cancelled(session: Session, payload: Dict[str, Any]) -> None:
    """The patient cancelled in the Endod app (and has been refunded there)."""
    booking = session.scalar(select(Booking).where(Booking.external_id == str(payload["appointment_id"]))
                             .with_for_update())
    if booking is None or booking.status not in BookingStatus.OPEN:
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
