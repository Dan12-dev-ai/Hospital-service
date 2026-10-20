"""Staff work on Endod bookings: the list, approve or reject video visits,
cancel or complete visits, and join a video visit (the assigned doctor)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import jitsi
from app.auth import Staff, audit, require_roles
from app.bookings import BookingError, approve_video, cancel, complete, reject
from app.db import ensure_aware, session_scope, utcnow
from app.models import Booking, BookingStatus, Hospital, Role, StaffUser, VisitMode
from app.validation import Name

router = APIRouter(prefix="/bookings", tags=["bookings"])

VIEWERS = (Role.ADMIN, Role.DOCTOR, Role.NURSE, Role.RECEPTION)
viewer = require_roles(*VIEWERS)


class Approval(BaseModel):
    #: An admin approves on behalf of a doctor; a doctor approves for themselves.
    doctor_id: Optional[str] = Field(default=None, max_length=32)


class Reason(BaseModel):
    reason: Name = Field(max_length=300)


def _payload(b: Booking, doctors: Dict[str, str]) -> Dict[str, Any]:
    return {
        "id": b.id,
        "external_id": b.external_id,
        "patient": {"dedan_id": b.patient_dedan_id, "name": b.patient_name, "phone": b.patient_phone},
        "visit_mode": b.visit_mode,
        "service": b.service,
        "scheduled_at": ensure_aware(b.scheduled_at).isoformat(),
        "duration_minutes": b.duration_minutes,
        "notes": b.notes,
        "price": f"{Decimal(b.price) / 100:.2f}",
        "status": b.status,
        "doctor": {"id": b.doctor_id, "full_name": doctors.get(b.doctor_id, "")} if b.doctor_id else None,
        "has_video_room": bool(b.meeting_room),
        "reason": b.reason,
        "decided_at": ensure_aware(b.decided_at).isoformat() if b.decided_at else None,
        "created_at": ensure_aware(b.created_at).isoformat(),
    }


def _names(session, bookings: List[Booking]) -> Dict[str, str]:
    ids = {b.doctor_id for b in bookings if b.doctor_id}
    if not ids:
        return {}
    return {u.id: u.full_name for u in session.scalars(select(StaffUser).where(StaffUser.id.in_(ids)))}


def _booking_for_update(session, staff: Staff, booking_id: str) -> Booking:
    booking = session.scalar(select(Booking).where(Booking.id == booking_id, Booking.hospital_id == staff.hospital_id)
                             .with_for_update())
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    return booking


def _decide(staff: Staff, booking_id: str, action, *args) -> Dict[str, Any]:
    try:
        with session_scope() as session:
            booking = _booking_for_update(session, staff, booking_id)
            action(session, booking, *args)
            audit(session, staff.hospital_id, staff.id, f"booking_{booking.status}", "booking", booking.id)
            session.flush()
            return _payload(booking, _names(session, [booking]))
    except BookingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("")
def list_bookings(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    mode: Optional[str] = None,
    day: Optional[date] = Query(default=None, description="Local date (hospital timezone)"),
    mine: bool = False,
    staff: Staff = Depends(viewer),
) -> Dict[str, Any]:
    if status_filter is not None and status_filter not in BookingStatus.ALL:
        raise HTTPException(status_code=400, detail=f"status must be one of {list(BookingStatus.ALL)}.")
    if mode is not None and mode not in VisitMode.ALL:
        raise HTTPException(status_code=400, detail=f"mode must be one of {list(VisitMode.ALL)}.")
    with session_scope() as session:
        query = select(Booking).where(Booking.hospital_id == staff.hospital_id)
        if status_filter:
            query = query.where(Booking.status == status_filter)
        if mode:
            query = query.where(Booking.visit_mode == mode)
        if mine:
            query = query.where(Booking.doctor_id == staff.id)
        if day:
            zone = ZoneInfo(session.get(Hospital, staff.hospital_id).timezone)
            start = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
            query = query.where(Booking.scheduled_at >= start, Booking.scheduled_at < start + timedelta(days=1))
        bookings = list(session.scalars(query.order_by(Booking.scheduled_at)))
        counts: Dict[str, int] = {s: 0 for s in BookingStatus.ALL}
        for status in session.scalars(select(Booking.status).where(Booking.hospital_id == staff.hospital_id)):
            counts[status] = counts.get(status, 0) + 1
        return {"items": [_payload(b, _names(session, bookings)) for b in bookings], "counts": counts}


@router.get("/{booking_id}")
def read_booking(booking_id: str, staff: Staff = Depends(viewer)) -> Dict[str, Any]:
    with session_scope() as session:
        booking = session.scalar(select(Booking).where(Booking.id == booking_id,
                                                       Booking.hospital_id == staff.hospital_id))
        if booking is None:
            raise HTTPException(status_code=404, detail="Booking not found.")
        return _payload(booking, _names(session, [booking]))


@router.post("/{booking_id}/approve")
def approve(booking_id: str, body: Approval,
            staff: Staff = Depends(require_roles(Role.DOCTOR, Role.ADMIN))) -> Dict[str, Any]:
    """A doctor approves a video visit and becomes its doctor (an admin names the doctor)."""
    doctor_id = staff.id if staff.role == Role.DOCTOR else body.doctor_id
    if not doctor_id:
        raise HTTPException(status_code=400, detail="Choose the doctor for this visit.")

    def action(session, booking):
        doctor = session.scalar(select(StaffUser).where(
            StaffUser.id == doctor_id, StaffUser.hospital_id == staff.hospital_id,
            StaffUser.role == Role.DOCTOR, StaffUser.active.is_(True)))
        if doctor is None:
            raise BookingError("Unknown doctor.")
        approve_video(session, booking, doctor, staff.id)

    return _decide(staff, booking_id, action)


@router.post("/{booking_id}/reject")
def reject_booking(booking_id: str, body: Reason,
                   staff: Staff = Depends(require_roles(Role.DOCTOR, Role.ADMIN, Role.RECEPTION))) -> Dict[str, Any]:
    return _decide(staff, booking_id, lambda s, b: reject(s, b, body.reason, staff.id))


@router.post("/{booking_id}/cancel")
def cancel_booking(booking_id: str, body: Reason,
                   staff: Staff = Depends(require_roles(Role.ADMIN, Role.RECEPTION, Role.DOCTOR))) -> Dict[str, Any]:
    return _decide(staff, booking_id, lambda s, b: cancel(s, b, body.reason, staff.id))


@router.post("/{booking_id}/complete")
def complete_booking(booking_id: str,
                     staff: Staff = Depends(require_roles(Role.DOCTOR, Role.NURSE, Role.ADMIN))) -> Dict[str, Any]:
    return _decide(staff, booking_id, lambda s, b: complete(s, b, staff.id))


@router.post("/{booking_id}/video")
def join_video(booking_id: str, staff: Staff = Depends(require_roles(Role.DOCTOR))) -> Dict[str, Any]:
    """Join details for the visit's own doctor, around the visit's time."""
    with session_scope() as session:
        booking = session.scalar(select(Booking).where(Booking.id == booking_id,
                                                       Booking.hospital_id == staff.hospital_id))
        if booking is None or booking.doctor_id != staff.id:
            raise HTTPException(status_code=404, detail="Booking not found.")
        if booking.status != BookingStatus.CONFIRMED or not booking.meeting_room:
            raise HTTPException(status_code=409, detail="This visit has no video room.")
        opens, closes = jitsi.join_window(ensure_aware(booking.scheduled_at), booking.duration_minutes)
        now = utcnow()
        if not opens <= now <= closes:
            raise HTTPException(status_code=409, detail="The video room opens 30 minutes before the visit.")
        try:
            details = jitsi.join_details(booking.meeting_room, staff.full_name, moderator=True)
        except jitsi.JitsiError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        audit(session, staff.hospital_id, staff.id, "booking_video_joined", "booking", booking.id)
        return details
