"""The onboarding wizard (a pending hospital's admin) and Endod's review of it.

For the hospital (signed in, admin, hospital pending; see app.onboarding):

* ``GET /onboarding/application``: the application, what is missing, where to resume;
* ``PATCH /onboarding/contact | facility | location | documents``: save a step;
* ``POST /onboarding/documents/{kind}``: upload or replace a document (the file
  is the body, its name in X-Filename); ``GET`` the same path to view it;
* ``GET /onboarding/demo-slots``, ``POST /onboarding/demo``: book or change the demo;
* ``POST /onboarding/submit``: send the application to Endod.

Steps can be saved while a draft or after Endod sent the application back;
the demo can be changed until the hospital is approved.

For Endod (``X-Platform-Key``): ``GET /platform/applications``,
``GET /platform/applications/{hospital_id}``, its documents, and
``POST /platform/hospitals/{hospital_id}/reject``. Approval is
``POST /platform/hospitals/{hospital_id}/approve`` (app.api.onboarding).
"""

from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import AwareDatetime, BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import crypto, eventbus, files, onboarding
from app.api.onboarding import platform_admin
from app.auth import Staff, audit, signed_in_staff
from app.db import ensure_aware, new_id, platform_session, session_scope, utcnow
from app.models import (
    ApplicationStatus, DemoBooking, DocumentKind, Hospital, HospitalStatus, OnboardingApplication,
    OnboardingDocument, Role, Service,
)
from app.validation import ContactNumber, Name, OptionalText, normalize_phone

router = APIRouter(tags=["onboarding"])

DEMO_EVENT = "onboarding.demo_booked"


NOT_APPLICANT = "Only the contact person who applied can change the application."


def applicant(staff: Staff = Depends(signed_in_staff)) -> Staff:
    """The contact person filling in the application: the admin who signed the
    hospital up. Other staff of a hospital still applying see only its status
    (GET /onboarding/status)."""
    if staff.must_change_password:
        raise HTTPException(status_code=403, detail="Change your temporary password to continue.")
    if staff.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail=NOT_APPLICANT)
    with session_scope(staff.hospital_id) as session:
        contact = onboarding.contact_person(session, staff.hospital_id)
        if contact is None or contact.id != staff.id:
            raise HTTPException(status_code=403, detail=NOT_APPLICANT)
    return staff


def _hospital(session, staff: Staff, lock: bool = False) -> Hospital:
    query = select(Hospital).where(Hospital.id == staff.hospital_id)
    if lock:
        query = query.with_for_update()
    return session.scalar(query)


# --- reading -------------------------------------------------------------------------------

@router.get("/onboarding/status")
def read_status(staff: Staff = Depends(signed_in_staff)) -> Dict[str, Any]:
    """Where the hospital is in onboarding, for anyone of its staff (the
    Under review page): read-only, without documents or contact details,
    except for the contact person themself."""
    with session_scope(staff.hospital_id) as session:
        hospital = _hospital(session, staff)
        onboarding.release_stale(session)
        app = onboarding.application_for(session, hospital)
        contact = onboarding.contact_person(session, hospital.id)
        is_applicant = contact is not None and contact.id == staff.id and staff.role == Role.ADMIN
        demo = onboarding.demo_of(session, hospital.id)
        return {
            "name": hospital.name,
            "status": onboarding.status_of(hospital, app),
            "hospital_status": hospital.status,
            "locked": staff.locked,
            "applicant": is_applicant,
            "must_change_password": staff.must_change_password,
            "submitted_at": ensure_aware(app.submitted_at).isoformat() if app.submitted_at else None,
            "rejection_reason": app.rejection_reason,
            "demo_at": onboarding.demo_iso(demo.slot_start) if demo else None,
            "contact_phone": contact.phone if is_applicant and contact else None,
        }


@router.get("/onboarding/application")
def read_application(staff: Staff = Depends(applicant)) -> Dict[str, Any]:
    with session_scope(staff.hospital_id) as session:
        return onboarding.application_payload(session, _hospital(session, staff))


# --- the steps -----------------------------------------------------------------------------

class ContactStep(BaseModel):
    full_name: Name = Field(max_length=120)
    title: Name = Field(max_length=80)
    #: An Ethiopian mobile: Endod texts the demo confirmation to it.
    phone: str = Field(max_length=32)

    @field_validator("phone")
    @classmethod
    def _mobile(cls, value: str) -> str:
        return normalize_phone(value)


class FacilityStep(BaseModel):
    facility_type: Literal["hospital", "clinic"]
    ownership: Literal["public", "private"]
    name: Name = Field(max_length=160)
    name_am: OptionalText = Field(default=None, max_length=160)
    city: Name = Field(max_length=100)
    phone: ContactNumber
    services: List[str] = Field(min_length=1, max_length=len(Service.ALL))
    open_hours: Name = Field(max_length=80)

    @field_validator("services")
    @classmethod
    def _services(cls, value: List[str]) -> List[str]:
        unknown = [s for s in value if s not in Service.ALL]
        if unknown:
            raise ValueError(f"unknown services {unknown}; use {list(Service.ALL)}")
        return list(dict.fromkeys(value))

    @field_validator("phone")
    @classmethod
    def _phone_given(cls, value: Optional[str]) -> str:
        if not value:
            raise ValueError("enter the facility's phone number")
        return value


class LocationStep(BaseModel):
    address: Name = Field(max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class DocumentsStep(BaseModel):
    license_number: Name = Field(max_length=60)


def _save_step(staff: Staff, step: str, apply) -> Dict[str, Any]:
    with session_scope(staff.hospital_id) as session:
        hospital = _hospital(session, staff, lock=True)
        app = onboarding.application_for(session, hospital, lock=True)
        onboarding.require_editable(hospital, app)
        apply(session, hospital, app)
        app.updated_at = utcnow()
        audit(session, hospital.id, staff.id, "onboarding_step_saved", "hospital", hospital.id, {"step": step})
        session.flush()
        return onboarding.application_payload(session, hospital)


@router.patch("/onboarding/contact")
def save_contact(body: ContactStep, staff: Staff = Depends(applicant)) -> Dict[str, Any]:
    def apply(session, hospital: Hospital, app: OnboardingApplication) -> None:
        contact = onboarding.contact_person(session, hospital.id)
        if contact is None:  # never: the hospital signed up with this account
            raise HTTPException(status_code=409, detail="The hospital has no contact person.")
        contact.full_name, contact.phone = body.full_name, body.phone
        app.contact_title = body.title
        booking = onboarding.demo_of(session, hospital.id)
        if booking is not None and booking.phone != body.phone:
            if _phone_taken(session, body.phone, hospital.id):
                raise HTTPException(status_code=409, detail=PHONE_TAKEN)
            booking.phone = body.phone

    return _save_step(staff, "contact", apply)


@router.patch("/onboarding/facility")
def save_facility(body: FacilityStep, staff: Staff = Depends(applicant)) -> Dict[str, Any]:
    def apply(_session, hospital: Hospital, _app) -> None:
        hospital.facility_type = body.facility_type
        hospital.kind = body.ownership
        hospital.name, hospital.name_am = body.name, body.name_am
        hospital.city, hospital.phone = body.city, body.phone
        hospital.services = ",".join(body.services)
        hospital.open_hours = body.open_hours

    return _save_step(staff, "facility", apply)


@router.patch("/onboarding/location")
def save_location(body: LocationStep, staff: Staff = Depends(applicant)) -> Dict[str, Any]:
    def apply(_session, hospital: Hospital, _app) -> None:
        hospital.address = body.address
        hospital.latitude, hospital.longitude = body.latitude, body.longitude

    return _save_step(staff, "location", apply)


@router.patch("/onboarding/documents")
def save_documents(body: DocumentsStep, staff: Staff = Depends(applicant)) -> Dict[str, Any]:
    def apply(_session, _hospital_row, app: OnboardingApplication) -> None:
        app.license_number = body.license_number

    return _save_step(staff, "documents", apply)


# --- documents -------------------------------------------------------------------------------

@router.post("/onboarding/documents/{kind}", status_code=status.HTTP_201_CREATED)
async def upload_document(kind: str, request: Request,
                          x_filename: Optional[str] = Header(default=None, max_length=600),
                          content_length: Optional[int] = Header(default=None),
                          staff: Staff = Depends(applicant)) -> Dict[str, Any]:
    """One document, as the request body. Uploading a kind again replaces it."""
    if kind not in DocumentKind.ALL:
        raise HTTPException(status_code=404, detail="Unknown document.")
    limit_mb = onboarding.MAX_DOCUMENT_BYTES // (1024 * 1024)
    if content_length is not None and content_length > onboarding.MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail=f"A document can be at most {limit_mb} MB.")

    def check() -> crypto.DataKey:
        with session_scope(staff.hospital_id) as session:
            hospital = _hospital(session, staff)
            onboarding.require_editable(hospital, onboarding.application_for(session, hospital))
            # Encrypted as it arrives, with the hospital's data key.
            return crypto.active_key(session, staff.hospital_id)

    key = await run_in_threadpool(check)
    file_id = new_id()
    try:
        size, sha256, content_type = await files.store_stream(
            request.stream(), staff.hospital_id, file_id, key, max_bytes=onboarding.MAX_DOCUMENT_BYTES)
        filename = files.safe_filename(unquote(x_filename or ""), content_type)
    except files.FileRejected as exc:
        files.delete(staff.hospital_id, file_id)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    def save() -> tuple:
        with session_scope(staff.hospital_id) as session:
            hospital = _hospital(session, staff, lock=True)
            # Checked again under the lock: the application may have been submitted meanwhile.
            onboarding.require_editable(hospital, onboarding.application_for(session, hospital, lock=True))
            old = session.scalar(select(OnboardingDocument).where(
                OnboardingDocument.hospital_id == hospital.id, OnboardingDocument.kind == kind))
            replaced = old.id if old is not None else None
            if old is not None:
                session.delete(old)
                session.flush()  # the old row goes before the new one takes its kind
            session.add(OnboardingDocument(id=file_id, hospital_id=hospital.id, kind=kind, filename=filename,
                                           content_type=content_type, size=size, sha256=sha256,
                                           uploaded_by=staff.id))
            audit(session, hospital.id, staff.id, "onboarding_document_uploaded", "hospital", hospital.id,
                  {"kind": kind, "sha256": sha256, "replaced": bool(replaced)})
            session.flush()
            return onboarding.application_payload(session, hospital), replaced

    try:
        payload, replaced = await run_in_threadpool(save)
    except IntegrityError as exc:
        files.delete(staff.hospital_id, file_id)
        raise HTTPException(status_code=409, detail="The document changed meanwhile; upload it again.") from exc
    except BaseException:
        files.delete(staff.hospital_id, file_id)
        raise
    if replaced:
        files.delete(staff.hospital_id, replaced)
    return payload


def _send(session, doc: OnboardingDocument):
    """The document, decrypted and checked against its sha256 before the
    first byte is sent."""
    try:
        plain = files.open_checked(session, doc.hospital_id, doc.id, doc.size, doc.sha256)
    except files.FileRejected as exc:
        raise HTTPException(status_code=404, detail="Document not found.") from exc
    return files.streaming_response(plain, doc.content_type, doc.filename, doc.sha256)


def _document(session, hospital_id: str, kind: str) -> OnboardingDocument:
    if kind not in DocumentKind.ALL:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc = session.scalar(select(OnboardingDocument).where(
        OnboardingDocument.hospital_id == hospital_id, OnboardingDocument.kind == kind))
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


@router.get("/onboarding/documents/{kind}")
def read_document(kind: str, staff: Staff = Depends(applicant)):
    """The hospital's own document (only its own: the hospital comes from the session)."""
    with session_scope(staff.hospital_id) as session:
        return _send(session, _document(session, staff.hospital_id, kind))


# --- the demo --------------------------------------------------------------------------------

class DemoChoice(BaseModel):
    #: A slot start from GET /onboarding/demo-slots, with its offset.
    demo_at: AwareDatetime


@router.get("/onboarding/demo-slots")
def demo_slots(staff: Staff = Depends(applicant)) -> Dict[str, Any]:
    with session_scope(staff.hospital_id) as session:
        demo = onboarding.demo_of(session, staff.hospital_id)
        return {
            "timezone": onboarding.DEMO_TIMEZONE,
            "minutes": onboarding.SLOT_MINUTES,
            "current": onboarding.demo_iso(demo.slot_start) if demo else None,
            "days": onboarding.free_slots(session, staff.hospital_id),
        }


SLOT_TAKEN = "Another hospital has just booked that time. Choose another one."
PHONE_TAKEN = ("This mobile number already has a demo booked for another facility. "
               "One person can hold one demo at a time.")
DOCUMENTS_FIRST = "Upload all four documents before booking a demo."


def _phone_taken(session, phone: str, hospital_id: str) -> bool:
    return onboarding.phone_taken(session, phone, hospital_id)


@router.post("/onboarding/demo")
def book_demo(body: DemoChoice, staff: Staff = Depends(applicant)) -> Dict[str, Any]:
    """Book the demo, or move it to another free slot (until the hospital is approved).

    The slot is unique across hospitals: of two hospitals racing for one, the
    second gets 409. Each booking or change is sent to the patient platform
    (onboarding.demo_booked), which texts the contact person.
    """
    slot = onboarding.as_slot(body.demo_at)
    if slot is None:
        raise HTTPException(status_code=400, detail="Choose one of the demo times on offer.")
    slot_utc = slot.astimezone(timezone.utc)
    try:
        with session_scope(staff.hospital_id) as session:
            hospital = _hospital(session, staff, lock=True)
            onboarding.require_pending(hospital)
            contact = onboarding.contact_person(session, hospital.id)
            if contact is None or not (contact.phone or "").startswith("+251"):
                raise HTTPException(status_code=400, detail="Add the contact person's mobile number first.")
            if len(onboarding.documents_of(session, hospital.id)) < len(DocumentKind.ALL):
                raise HTTPException(status_code=400, detail=DOCUMENTS_FIRST)
            # Stale bookings (anyone's) give their slot and phone back first.
            onboarding.release_stale(session)
            booking = onboarding.demo_of(session, hospital.id)
            if booking is not None and ensure_aware(booking.slot_start) == slot_utc:
                return onboarding.application_payload(session, hospital)
            if slot_utc in onboarding.taken_slots(session, except_hospital=hospital.id):
                raise HTTPException(status_code=409, detail=SLOT_TAKEN)
            if _phone_taken(session, contact.phone, hospital.id):
                raise HTTPException(status_code=409, detail=PHONE_TAKEN)
            changed = booking is not None
            if booking is None:
                # Booked "now" on the same clock that releases it (app.onboarding.now).
                booking = DemoBooking(id=new_id(), hospital_id=hospital.id, slot_start=slot_utc,
                                      phone=contact.phone, created_at=onboarding.now())
                session.add(booking)
            else:
                booking.slot_start = slot_utc
            # The unique slot (and phone) settle a race: the losing insert or update fails here.
            session.flush()
            eventbus.emit(session, DEMO_EVENT, {
                "hospital_id": hospital.id,
                "booking_id": booking.id,
                "contact_name": contact.full_name,
                "phone": contact.phone,
                "demo_at": slot.isoformat(),
                "hospital_name": hospital.name,
                "changed": changed,
            })
            audit(session, hospital.id, staff.id, "onboarding_demo_booked", "hospital", hospital.id,
                  {"demo_at": slot.isoformat(), "changed": changed})
            session.flush()
            return onboarding.application_payload(session, hospital)
    except IntegrityError as exc:
        with session_scope(staff.hospital_id) as session:
            contact = onboarding.contact_person(session, staff.hospital_id)
            phone_lost = bool(contact is not None and contact.phone
                              and _phone_taken(session, contact.phone, staff.hospital_id))
        raise HTTPException(status_code=409, detail=PHONE_TAKEN if phone_lost else SLOT_TAKEN) from exc


# --- submitting ----------------------------------------------------------------------------

STEP_NAMES = {"contact": "contact person", "facility": "facility", "location": "location",
              "documents": "documents", "demo": "demo booking"}


@router.post("/onboarding/submit")
def submit(staff: Staff = Depends(applicant)) -> Dict[str, Any]:
    with session_scope(staff.hospital_id) as session:
        hospital = _hospital(session, staff, lock=True)
        app = onboarding.application_for(session, hospital, lock=True)
        onboarding.require_editable(hospital, app)
        gaps = onboarding.missing(session, hospital, app)
        unfinished = [STEP_NAMES[step] for step in onboarding.STEPS if gaps[step]]
        if unfinished:
            raise HTTPException(status_code=400, detail=f"Finish these steps first: {', '.join(unfinished)}.")
        app.status = ApplicationStatus.SUBMITTED
        app.submitted_at = utcnow()
        app.rejection_reason = None
        audit(session, hospital.id, staff.id, "onboarding_submitted", "hospital", hospital.id)
        session.flush()
        return onboarding.application_payload(session, hospital)


# --- Endod ---------------------------------------------------------------------------------

def _summary(session, hospital: Hospital, app: Optional[OnboardingApplication]) -> Dict[str, Any]:
    contact = onboarding.contact_person(session, hospital.id)
    demo = onboarding.demo_of(session, hospital.id)
    status_value = (onboarding.status_of(hospital, app) if app is not None
                    else ApplicationStatus.APPROVED if hospital.status == HospitalStatus.APPROVED
                    else ApplicationStatus.DRAFT)
    return {
        "hospital_id": hospital.id,
        "code": hospital.code,
        "name": hospital.name,
        "facility_type": hospital.facility_type,
        "ownership": hospital.kind,
        "city": hospital.city,
        "status": status_value,
        "hospital_status": hospital.status,
        "created_at": ensure_aware(hospital.created_at).isoformat(),
        "submitted_at": ensure_aware(app.submitted_at).isoformat() if app and app.submitted_at else None,
        "demo_at": onboarding.demo_iso(demo.slot_start) if demo else None,
        "contact": None if contact is None else {
            "name": contact.full_name, "title": app.contact_title if app else None,
            "email": contact.email, "phone": contact.phone,
        },
    }


@router.get("/platform/applications", dependencies=[Depends(platform_admin)])
def list_applications(status_filter: Optional[str] = Query(default=None, alias="status")) -> List[Dict[str, Any]]:
    """Every hospital that applied through the portal (pending, or approved since)."""
    if status_filter is not None and status_filter not in ApplicationStatus.ALL:
        raise HTTPException(status_code=400, detail=f"status must be one of {list(ApplicationStatus.ALL)}.")
    with platform_session() as session:
        rows = session.execute(
            select(Hospital, OnboardingApplication)
            .outerjoin(OnboardingApplication, OnboardingApplication.hospital_id == Hospital.id)
            .where((Hospital.status == HospitalStatus.PENDING) | OnboardingApplication.hospital_id.is_not(None))
            .order_by(Hospital.created_at.desc())
        ).all()
        result = [_summary(session, hospital, app) for hospital, app in rows]
    return [row for row in result if status_filter is None or row["status"] == status_filter]


def _applied_hospital(session, hospital_id: str, lock: bool = False) -> Hospital:
    query = select(Hospital).where(Hospital.id == hospital_id)
    if lock:
        query = query.with_for_update()
    hospital = session.scalar(query)
    if hospital is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    return hospital


@router.get("/platform/applications/{hospital_id}", dependencies=[Depends(platform_admin)])
def read_application_for_endod(hospital_id: str) -> Dict[str, Any]:
    with platform_session() as session:
        hospital = _applied_hospital(session, hospital_id)
        payload = onboarding.application_payload(session, hospital)
        for item in payload["documents"]["items"]:
            if item["uploaded"]:
                item["download"] = f"/platform/applications/{hospital.id}/documents/{item['kind']}"
        payload["name"] = hospital.name
        return payload


@router.get("/platform/applications/{hospital_id}/documents/{kind}", dependencies=[Depends(platform_admin)])
def read_document_for_endod(hospital_id: str, kind: str):
    with platform_session() as session:
        hospital = _applied_hospital(session, hospital_id)
        return _send(session, _document(session, hospital.id, kind))


class Rejection(BaseModel):
    #: Shown to the hospital on its Under review page.
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("give a reason the hospital can act on")
        return value


@router.post("/platform/hospitals/{hospital_id}/reject", dependencies=[Depends(platform_admin)])
def reject(hospital_id: str, body: Rejection) -> Dict[str, Any]:
    """Send a submitted application back with a reason; the hospital fixes it and resubmits."""
    with platform_session() as session:
        hospital = _applied_hospital(session, hospital_id, lock=True)
        app = onboarding.application_for(session, hospital, lock=True)
        if hospital.status != HospitalStatus.PENDING or app.status != ApplicationStatus.SUBMITTED:
            raise HTTPException(status_code=409, detail="Only a submitted application can be sent back.")
        app.status = ApplicationStatus.REJECTED
        app.rejection_reason = body.reason
        app.rejected_at = utcnow()
        # The demo slot goes back to the calendar; they book again when they resubmit.
        onboarding.release_demo(session, hospital.id)
        audit(session, hospital.id, None, "onboarding_rejected", "hospital", hospital.id, {"reason": body.reason})
        session.flush()
        return onboarding.application_payload(session, hospital)

