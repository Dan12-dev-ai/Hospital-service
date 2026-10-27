"""A hospital's application to join Endod: what it filled in, what is missing,
its documents and its demo with Endod.

The wizard in the portal saves each step through app.api.onboarding; nothing
here is visible to patients. The steps, in the order the portal shows them:

1. ``contact``: the contact person, who is also the first admin account
   (created by ``POST /onboarding``, so uploads have an owner);
2. ``facility``: kind, ownership, name, city, phone, services, opening hours;
3. ``location``: address and a pin on the map;
4. ``documents``: the four required documents and the license number;
5. ``demo``: a 30-minute demo with Endod;
6. ``review``: submit.

Demo slots are 30 minutes, Monday to Friday, 09:00 to 17:00 Addis Ababa time,
from tomorrow to 30 days ahead. Times are stored in UTC.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import ensure_aware, utcnow
from app.models import (
    ApplicationStatus, DemoBooking, DocumentKind, Hospital, HospitalStatus, OnboardingApplication,
    OnboardingDocument, Role, Service, StaffUser,
)

#: Endod runs demos on Addis Ababa time, whatever the hospital's own timezone.
DEMO_TIMEZONE = "Africa/Addis_Ababa"
DEMO_TZ = ZoneInfo(DEMO_TIMEZONE)
SLOT_MINUTES = 30
DAY_START = time(9, 0)
DAY_END = time(17, 0)
DAYS_AHEAD = 30
#: Documents are smaller than clinical files.
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
#: A booked demo is released unless the application is submitted within this.
SUBMIT_WITHIN = timedelta(hours=24)

STEPS = ("contact", "facility", "location", "documents", "demo")


def now() -> datetime:
    """The current time (tests replace this to pin the calendar)."""
    return utcnow()


# --- demo slots -------------------------------------------------------------------------

def slot_grid(at: Optional[datetime] = None) -> Iterator[datetime]:
    """Every demo slot start (Addis time) from tomorrow to DAYS_AHEAD days ahead."""
    today = (at or now()).astimezone(DEMO_TZ).date()
    for offset in range(1, DAYS_AHEAD + 1):
        day = today + timedelta(days=offset)
        if day.weekday() >= 5:  # Saturday, Sunday
            continue
        start = datetime.combine(day, DAY_START, tzinfo=DEMO_TZ)
        end = datetime.combine(day, DAY_END, tzinfo=DEMO_TZ)
        while start + timedelta(minutes=SLOT_MINUTES) <= end:
            yield start
            start += timedelta(minutes=SLOT_MINUTES)


def as_slot(value: datetime) -> Optional[datetime]:
    """``value`` as a slot start in Addis time if it is one on offer now, else None."""
    if value.tzinfo is None:
        return None
    wanted = value.astimezone(DEMO_TZ)
    for slot in slot_grid():
        if slot == wanted:
            return slot
    return None


def demo_iso(value: datetime) -> str:
    """A stored (UTC) time as ISO-8601 in Addis time, with its offset."""
    return ensure_aware(value).astimezone(DEMO_TZ).isoformat()


def release_stale(session: Session) -> int:
    """Release (delete) demo bookings that hold a slot for nothing: the
    application was not submitted within SUBMIT_WITHIN of booking, or the
    hospital was suspended before approval. Their slot and phone are free
    again, and nothing more is sent about them. Returns how many.

    Any hospital's: an applicant's calendar must not show a slot held by a
    stale booking of another. On PostgreSQL that is the one fixed delete of
    release_stale_demo_bookings (app/rls.py), not a platform transaction."""
    if _postgres(session):
        return session.scalar(text("SELECT release_stale_demo_bookings(:cutoff)"),
                              {"cutoff": now() - SUBMIT_WITHIN}) or 0
    unsubmitted = select(OnboardingApplication.hospital_id).where(
        OnboardingApplication.status.in_(ApplicationStatus.EDITABLE))
    suspended = select(Hospital.id).join(OnboardingApplication, OnboardingApplication.hospital_id == Hospital.id).where(
        Hospital.status == HospitalStatus.SUSPENDED, OnboardingApplication.status != ApplicationStatus.APPROVED)
    result = session.execute(delete(DemoBooking).where(or_(
        (DemoBooking.hospital_id.in_(unsubmitted)) & (DemoBooking.created_at < now() - SUBMIT_WITHIN),
        DemoBooking.hospital_id.in_(suspended),
    )).execution_options(synchronize_session=False))
    return result.rowcount or 0


def release_demo(session: Session, hospital_id: str) -> None:
    """Release the hospital's demo now (its application was sent back or suspended)."""
    session.execute(delete(DemoBooking).where(DemoBooking.hospital_id == hospital_id)
                    .execution_options(synchronize_session=False))


def taken_slots(session: Session, except_hospital: Optional[str] = None) -> set:
    """Slot starts (UTC) booked by other hospitals, from today on (only the
    times: demo_slots_taken on PostgreSQL)."""
    since = now() - timedelta(days=1)
    if _postgres(session):
        values = session.scalars(text("SELECT demo_slots_taken(:hospital, :since)"),
                                 {"hospital": except_hospital, "since": since})
    else:
        query = select(DemoBooking.slot_start).where(DemoBooking.slot_start >= since)
        if except_hospital:
            query = query.where(DemoBooking.hospital_id != except_hospital)
        values = session.scalars(query)
    return {ensure_aware(value).astimezone(timezone.utc) for value in values}


def phone_taken(session: Session, phone: str, hospital_id: str) -> bool:
    """Whether another hospital's demo holds this mobile (a yes or no only)."""
    if _postgres(session):
        return bool(session.scalar(text("SELECT demo_phone_taken(:phone, :hospital)"),
                                   {"phone": phone, "hospital": hospital_id}))
    return session.scalar(select(DemoBooking.id).where(
        DemoBooking.phone == phone, DemoBooking.hospital_id != hospital_id)) is not None


def _postgres(session: Session) -> bool:
    """Other hospitals' demo bookings are read through the narrow functions of
    app/rls.py there (row-level security hides them otherwise)."""
    return session.get_bind().dialect.name == "postgresql"


def free_slots(session: Session, hospital_id: str) -> List[Dict[str, Any]]:
    """The calendar: each weekday with its free slots (another hospital's are hidden)."""
    release_stale(session)
    taken = taken_slots(session, except_hospital=hospital_id)
    days: Dict[date, List[str]] = {}
    for slot in slot_grid():
        day = days.setdefault(slot.date(), [])
        if slot.astimezone(timezone.utc) not in taken:
            day.append(slot.isoformat())
    return [{"date": day.isoformat(), "slots": slots} for day, slots in days.items()]


# --- the application ---------------------------------------------------------------------

def application_for(session: Session, hospital: Hospital, lock: bool = False) -> OnboardingApplication:
    """The hospital's application (created for a hospital that signed up before applications existed)."""
    query = select(OnboardingApplication).where(OnboardingApplication.hospital_id == hospital.id)
    if lock:
        query = query.with_for_update()
    app = session.scalar(query)
    if app is None:
        # A hospital that predates applications: pending ones still apply;
        # others (approved, or approved once and suspended since) were approved.
        app = OnboardingApplication(
            hospital_id=hospital.id,
            status=ApplicationStatus.DRAFT if hospital.status == HospitalStatus.PENDING
            else ApplicationStatus.APPROVED)
        try:
            # A savepoint: two first requests at once must not fail the outer transaction.
            with session.begin_nested():
                session.add(app)
        except IntegrityError:
            app = session.scalar(query)
    return app


def contact_person(session: Session, hospital_id: str) -> Optional[StaffUser]:
    """The contact person: the hospital's first admin (who signed it up)."""
    return session.scalar(select(StaffUser).where(StaffUser.hospital_id == hospital_id, StaffUser.role == Role.ADMIN)
                          .order_by(StaffUser.created_at, StaffUser.id).limit(1))


def documents_of(session: Session, hospital_id: str) -> Dict[str, OnboardingDocument]:
    return {d.kind: d for d in session.scalars(
        select(OnboardingDocument).where(OnboardingDocument.hospital_id == hospital_id))}


def demo_of(session: Session, hospital_id: str) -> Optional[DemoBooking]:
    return session.scalar(select(DemoBooking).where(DemoBooking.hospital_id == hospital_id))


def services_list(hospital: Hospital) -> List[str]:
    return [s for s in (hospital.services or "").split(",") if s in Service.ALL]


def missing(session: Session, hospital: Hospital, app: OnboardingApplication) -> Dict[str, List[str]]:
    """What each step still needs (an empty list: the step is complete)."""
    contact = contact_person(session, hospital.id)
    docs = documents_of(session, hospital.id)
    result: Dict[str, List[str]] = {step: [] for step in STEPS}
    if contact is None or not contact.full_name:
        result["contact"].append("full_name")
    if not app.contact_title:
        result["contact"].append("title")
    if contact is None or not (contact.phone or "").startswith("+251"):
        result["contact"].append("phone")
    for field in ("city", "phone", "open_hours"):
        if not getattr(hospital, field):
            result["facility"].append(field)
    if not services_list(hospital):
        result["facility"].append("services")
    if not hospital.address:
        result["location"].append("address")
    if hospital.latitude is None or hospital.longitude is None:
        result["location"].append("map_pin")
    result["documents"] = [kind for kind in DocumentKind.ALL if kind not in docs]
    if not app.license_number:
        result["documents"].append("license_number")
    demo = demo_of(session, hospital.id)
    # A demo whose time has passed (say, before a rejection) must be booked again.
    if demo is None or ensure_aware(demo.slot_start) <= now():
        result["demo"].append("demo_at")
    return result


def status_of(hospital: Hospital, app: OnboardingApplication) -> str:
    """The application's status; "suspended" for an applicant Endod suspended before approving it."""
    if app.status == ApplicationStatus.APPROVED:
        return ApplicationStatus.APPROVED
    if hospital.status == HospitalStatus.SUSPENDED:
        return "suspended"
    return app.status


def _iso(value: Optional[datetime]) -> Optional[str]:
    return ensure_aware(value).isoformat() if value else None


def document_payload(kind: str, doc: Optional[OnboardingDocument]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"kind": kind, "label": DocumentKind.LABELS[kind], "uploaded": doc is not None}
    if doc is not None:
        payload.update({"filename": doc.filename, "content_type": doc.content_type, "size": doc.size,
                        "sha256": doc.sha256, "uploaded_at": _iso(doc.uploaded_at)})
    return payload


def application_payload(session: Session, hospital: Hospital) -> Dict[str, Any]:
    """Everything the wizard and the Under review page show (and Endod reviews)."""
    release_stale(session)
    app = application_for(session, hospital)
    contact = contact_person(session, hospital.id)
    docs = documents_of(session, hospital.id)
    demo = demo_of(session, hospital.id)
    gaps = missing(session, hospital, app)
    next_step = next((step for step in STEPS if gaps[step]), "review")
    return {
        "hospital_id": hospital.id,
        "code": hospital.code,
        "status": status_of(hospital, app),
        "hospital_status": hospital.status,
        "next_step": next_step,
        "missing": gaps,
        "complete": next_step == "review",
        "created_at": _iso(hospital.created_at),
        "submitted_at": _iso(app.submitted_at),
        "rejected_at": _iso(app.rejected_at),
        "rejection_reason": app.rejection_reason,
        "contact": {
            "full_name": contact.full_name if contact else None,
            "title": app.contact_title,
            "phone": contact.phone if contact else None,
            "email": contact.email if contact else None,
        },
        "facility": {
            "facility_type": hospital.facility_type,
            "ownership": hospital.kind,
            "name": hospital.name,
            "name_am": hospital.name_am,
            "city": hospital.city,
            "phone": hospital.phone,
            "services": services_list(hospital),
            "open_hours": hospital.open_hours,
        },
        "location": {"address": hospital.address, "latitude": hospital.latitude, "longitude": hospital.longitude},
        "documents": {
            "license_number": app.license_number,
            "items": [document_payload(kind, docs.get(kind)) for kind in DocumentKind.ALL],
        },
        "demo": None if demo is None else {
            "booking_id": demo.id,
            "demo_at": demo_iso(demo.slot_start),
            "timezone": DEMO_TIMEZONE,
            "minutes": SLOT_MINUTES,
        },
    }


def require_pending(hospital: Hospital) -> None:
    if hospital.status == HospitalStatus.SUSPENDED:
        raise HTTPException(status_code=409, detail="Endod has suspended this application. Contact Endod.")
    if hospital.status != HospitalStatus.PENDING:
        raise HTTPException(status_code=409, detail="Your hospital is already approved; use the portal's settings.")


def require_editable(hospital: Hospital, app: OnboardingApplication) -> None:
    """The application can change only while a draft, or after Endod sent it back."""
    require_pending(hospital)
    if app.status not in ApplicationStatus.EDITABLE:
        raise HTTPException(status_code=409, detail="Your application is with Endod for review. "
                                                    "You can still change the demo time.")
