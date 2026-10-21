"""A patient's history: linking to Endod, visits and follow-ups, clinical
records and their files (docs/history-events.md, sections 1 to 3).

Role rules (backend-hospital/app/api/patients.py has the shared ones):

* reception, records staff and admins link and unlink patients (identity);
* doctors and nurses write every kind of record and open visits; only a
  doctor sets a follow-up;
* records staff and admins file documents and lab results (with files);
* clinical details are read by DIAGNOSIS_READERS only (not reception or billing).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import func, select

from app import files, linking, records
from app.api.onboarding import platform_admin
from app.api.patients import DEMOGRAPHIC_EDITORS, DIAGNOSIS_READERS
from app.auth import Staff, audit, current_staff, require_roles
from app.db import new_id, session_scope, utcnow
from app.models import (
    Booking, ClinicalRecord, Hospital, Patient, PatientLinkRequest, RecordCategory, RecordFile, Role,
    StaffUser, Visit,
)
from app.validation import Name, OptionalPhone, OptionalText, normalize_dedan_id

router = APIRouter(tags=["patient history"])
platform_router = APIRouter(tags=["platform"])

#: Who links a patient to Endod (an identity change, like the Endod ID used to be).
LINKERS = DEMOGRAPHIC_EDITORS
#: Who writes clinical records of every kind, and opens visits.
RECORD_WRITERS = (Role.DOCTOR, Role.NURSE)
#: Who files documents and lab results (scans, the lab's reports).
DOCUMENT_FILERS = (Role.ADMIN, Role.RECORDS)
DOCUMENT_CATEGORIES = (RecordCategory.DOCUMENT, RecordCategory.LAB_RESULT)
#: Who reads clinical records and their files: the same people as the working diagnosis.
RECORD_READERS = DIAGNOSIS_READERS
#: Who sets a follow-up.
FOLLOW_UP_SETTERS = (Role.DOCTOR,)
#: Files one person may have uploaded and not yet attached.
MAX_PENDING_UPLOADS = 30

readers = require_roles(*RECORD_READERS)


def _may_write(role: str, category: str) -> bool:
    return role in RECORD_WRITERS or (role in DOCUMENT_FILERS and category in DOCUMENT_CATEGORIES)


def _patient(session, staff: Staff, patient_id: str, lock: bool = False) -> Patient:
    query = select(Patient).where(Patient.id == patient_id, Patient.hospital_id == staff.hospital_id)
    patient = session.scalar(query.with_for_update() if lock else query)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return patient


def _iso(value: Optional[datetime]) -> Optional[str]:
    return records.iso(value) if value else None


# --- linking -----------------------------------------------------------------------------

class LinkBody(BaseModel):
    #: The health card's QR (https://endod-health.com/card/<ID>?s=...).
    card_url: OptionalText = Field(default=None, max_length=700)
    dedan_id: OptionalText = Field(default=None, max_length=16)
    #: The phone number on the Endod account (with the Endod ID).
    phone: OptionalPhone = None


def _link_payload(session, patient: Patient) -> Dict[str, Any]:
    latest = session.scalar(select(PatientLinkRequest).where(PatientLinkRequest.patient_id == patient.id)
                            .order_by(PatientLinkRequest.created_at.desc(), PatientLinkRequest.id).limit(1))
    request = None
    if latest is not None:
        request = {"id": latest.id, "dedan_id": latest.dedan_id, "method": latest.method, "status": latest.status,
                   "reason": latest.reason, "linked_name": latest.linked_name,
                   "created_at": _iso(latest.created_at), "decided_at": _iso(latest.decided_at)}
    return {"patient_id": patient.id, "dedan_id": patient.dedan_id, "claimed_dedan_id": patient.claimed_dedan_id,
            "request": request}


@router.get("/patients/{patient_id}/link")
def link_status(patient_id: str, staff: Staff = Depends(current_staff)) -> Dict[str, Any]:
    with session_scope() as session:
        return _link_payload(session, _patient(session, staff, patient_id))


@router.post("/patients/{patient_id}/link", status_code=status.HTTP_202_ACCEPTED)
def request_link(patient_id: str, body: LinkBody, staff: Staff = Depends(require_roles(*LINKERS))) -> Dict[str, Any]:
    """Ask Endod to confirm the patient's account: by the card's QR, or by the
    Endod ID and the account's phone number. The answer arrives as an event."""
    signature = None
    if body.card_url:
        try:
            dedan_id, signature = linking.parse_card_url(body.card_url)
        except linking.LinkError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    else:
        if not body.dedan_id or not body.phone:
            raise HTTPException(status_code=400, detail="Give the Endod ID and the phone number on the account, "
                                                        "or scan the health card.")
        try:
            dedan_id = normalize_dedan_id(body.dedan_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Not a valid Endod ID, e.g. DE482731.") from exc
    with session_scope() as session:
        patient = _patient(session, staff, patient_id, lock=True)
        try:
            request = linking.request_link(session, patient, dedan_id, staff.id, card_signature=signature,
                                           phone=body.phone)
        except linking.LinkError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        audit(session, staff.hospital_id, staff.id, "patient_link_requested", "patient", patient.id,
              {"dedan_id": dedan_id, "method": request.method, "request_id": request.id})
        session.flush()
        return _link_payload(session, patient)


@router.delete("/patients/{patient_id}/link")
def unlink(patient_id: str, staff: Staff = Depends(require_roles(*LINKERS))) -> Dict[str, Any]:
    """Unlink (nothing more is sent to Endod), or withdraw a pending request."""
    with session_scope() as session:
        patient = _patient(session, staff, patient_id, lock=True)
        old = linking.unlink(session, patient)
        audit(session, staff.hospital_id, staff.id, "patient_unlinked" if old else "patient_link_withdrawn",
              "patient", patient.id, {"identity": {"dedan_id": {"from": old, "to": None}}} if old else None)
        session.flush()
        return _link_payload(session, patient)


# --- uploads --------------------------------------------------------------------------------

@router.post("/patients/{patient_id}/uploads", status_code=status.HTTP_201_CREATED)
async def upload(patient_id: str, request: Request,
                 x_filename: Optional[str] = Header(default=None, max_length=600),
                 content_length: Optional[int] = Header(default=None),
                 staff: Staff = Depends(require_roles(*(RECORD_WRITERS + DOCUMENT_FILERS)))) -> Dict[str, Any]:
    """One file, as the request body (the portal sends each file of a form
    this way). Attached to a record when the record is saved."""
    if content_length is not None and content_length > files.MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="A file can be at most 20 MB.")

    def check() -> None:
        with session_scope() as session:
            _patient(session, staff, patient_id)
            pending = session.scalar(select(func.count()).where(
                RecordFile.uploaded_by == staff.id, RecordFile.record_id.is_(None),
                RecordFile.created_at > utcnow() - timedelta(days=1))) or 0
            if pending >= MAX_PENDING_UPLOADS:
                raise HTTPException(status_code=429, detail="Too many files waiting to be attached. "
                                                            "Save or discard your records first.")

    await run_in_threadpool(check)
    file_id = new_id()
    try:
        size, sha256, content_type = await files.store_stream(request.stream(), staff.hospital_id, file_id)
        filename = files.safe_filename(unquote(x_filename or ""), content_type)
    except files.FileRejected as exc:
        files.delete(staff.hospital_id, file_id)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    def save() -> Dict[str, Any]:
        with session_scope() as session:
            row = RecordFile(id=file_id, hospital_id=staff.hospital_id, patient_id=patient_id, filename=filename,
                             content_type=content_type, size=size, sha256=sha256, uploaded_by=staff.id)
            session.add(row)
            return _file_payload(row)

    try:
        return await run_in_threadpool(save)
    except Exception:
        files.delete(staff.hospital_id, file_id)
        raise


def _file_payload(f: RecordFile) -> Dict[str, Any]:
    return {"id": f.id, "filename": f.filename, "content_type": f.content_type, "size": f.size, "sha256": f.sha256}


# --- records ----------------------------------------------------------------------------------

class RecordCreate(BaseModel):
    category: str
    title: Name = Field(max_length=200)
    details: Dict[str, Any] = Field(default_factory=dict)
    #: When it happened (default: now).
    occurred_at: Optional[AwareDatetime] = None
    visit_id: OptionalText = Field(default=None, max_length=32)
    file_ids: List[str] = Field(default_factory=list, max_length=files.MAX_FILES_PER_RECORD)


class RecordCorrection(BaseModel):
    title: Optional[Name] = Field(default=None, max_length=200)
    details: Optional[Dict[str, Any]] = None
    occurred_at: Optional[AwareDatetime] = None
    add_file_ids: List[str] = Field(default_factory=list, max_length=files.MAX_FILES_PER_RECORD)
    remove_file_ids: List[str] = Field(default_factory=list, max_length=files.MAX_FILES_PER_RECORD)


class Retraction(BaseModel):
    reason: Name = Field(max_length=300)


def _when(value: Optional[datetime]) -> datetime:
    if value is None:
        return utcnow()
    if value > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(status_code=400, detail="occurred_at cannot be in the future.")
    return value.astimezone(timezone.utc)


def _record_payload(session, r: ClinicalRecord) -> Dict[str, Any]:
    return {
        "id": r.id, "patient_id": r.patient_id, "visit_id": r.visit_id, "category": r.category, "title": r.title,
        "details": json.loads(r.details), "occurred_at": _iso(r.occurred_at), "recorded_by": r.recorded_by_name,
        "source": r.source, "version": r.version, "retracted": r.retracted, "retracted_reason": r.retracted_reason,
        "retracted_at": _iso(r.retracted_at),
        # Endod has this version (a correction made while unlinked is sent on re-linking).
        "published": bool(r.published_dedan_id) and r.published_version == r.version and not r.retracted,
        "published_version": r.published_version,
        "files": [_file_payload(f) for f in records.files_of(session, r.id)],
        "created_at": _iso(r.created_at), "updated_at": _iso(r.updated_at),
    }


def _attach(session, staff: Staff, record: ClinicalRecord, file_ids: List[str]) -> None:
    ids = list(dict.fromkeys(file_ids))
    if not ids:
        return
    found = list(session.scalars(select(RecordFile).where(
        RecordFile.id.in_(ids), RecordFile.hospital_id == staff.hospital_id,
        RecordFile.patient_id == record.patient_id, RecordFile.record_id.is_(None),
        RecordFile.uploaded_by == staff.id)))
    if len(found) != len(ids):
        raise HTTPException(status_code=400, detail="A file was not found; upload it again.")
    current = session.scalar(select(func.count()).where(RecordFile.record_id == record.id)) or 0
    if current + len(found) > files.MAX_FILES_PER_RECORD:
        raise HTTPException(status_code=400, detail=f"A record can have at most {files.MAX_FILES_PER_RECORD} files.")
    for f in found:
        f.record_id = record.id


def _clean(category: str, details: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return records.clean_details(category, details)
    except records.DetailsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/patients/{patient_id}/records")
def list_records(patient_id: str, staff: Staff = Depends(readers)) -> Dict[str, Any]:
    with session_scope() as session:
        patient = _patient(session, staff, patient_id)
        rows = session.scalars(select(ClinicalRecord).where(ClinicalRecord.patient_id == patient.id)
                               .order_by(ClinicalRecord.occurred_at.desc(), ClinicalRecord.created_at.desc()))
        audit(session, staff.hospital_id, staff.id, "patient_records_viewed", "patient", patient.id)
        return {"items": [_record_payload(session, r) for r in rows], "linked": bool(patient.dedan_id)}


@router.post("/patients/{patient_id}/records", status_code=status.HTTP_201_CREATED)
def create_record(patient_id: str, body: RecordCreate, staff: Staff = Depends(current_staff)) -> Dict[str, Any]:
    if body.category not in RecordCategory.ALL:
        raise HTTPException(status_code=400, detail=f"category must be one of {list(RecordCategory.ALL)}.")
    if not _may_write(staff.role, body.category):
        raise HTTPException(status_code=403, detail="Your role cannot add this kind of record.")
    if body.category == RecordCategory.DOCUMENT and not body.file_ids:
        raise HTTPException(status_code=400, detail="Attach the document's file.")
    details = _clean(body.category, body.details)
    occurred_at = _when(body.occurred_at)
    with session_scope() as session:
        patient = _patient(session, staff, patient_id, lock=True)
        if body.visit_id and session.scalar(select(Visit.id).where(
                Visit.id == body.visit_id, Visit.patient_id == patient.id)) is None:
            raise HTTPException(status_code=400, detail="Unknown visit.")
        author = session.get(StaffUser, staff.id)
        record = ClinicalRecord(
            hospital_id=staff.hospital_id, patient_id=patient.id, visit_id=body.visit_id, category=body.category,
            title=body.title, details=json.dumps(details, ensure_ascii=False), occurred_at=occurred_at,
            recorded_by=staff.id, recorded_by_name=author.full_name, source="portal", version=1,
        )
        session.add(record)
        session.flush()
        _attach(session, staff, record, body.file_ids)
        session.flush()
        records.publish(session, record, patient, session.get(Hospital, staff.hospital_id))
        audit(session, staff.hospital_id, staff.id, "record_added", "patient", patient.id,
              {"record_id": record.id, "category": record.category})
        session.flush()
        return _record_payload(session, record)


def _record_for_update(session, staff: Staff, record_id: str) -> ClinicalRecord:
    record = session.scalar(select(ClinicalRecord).where(
        ClinicalRecord.id == record_id, ClinicalRecord.hospital_id == staff.hospital_id).with_for_update())
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found.")
    if not _may_write(staff.role, record.category):
        raise HTTPException(status_code=403, detail="Your role cannot change this kind of record.")
    return record


@router.patch("/records/{record_id}")
def correct_record(record_id: str, body: RecordCorrection, staff: Staff = Depends(current_staff)) -> Dict[str, Any]:
    """A correction: a new version, sent to Endod again."""
    changes = body.model_dump(exclude_unset=True)
    if not any(changes.get(k) for k in ("title", "details", "occurred_at", "add_file_ids", "remove_file_ids")):
        raise HTTPException(status_code=400, detail="Nothing to change.")
    with session_scope() as session:
        record = _record_for_update(session, staff, record_id)
        if record.retracted:
            raise HTTPException(status_code=409, detail="A retracted record cannot be corrected.")
        patient = _patient(session, staff, record.patient_id, lock=True)
        if body.title:
            record.title = body.title
        if body.details is not None:
            record.details = json.dumps(_clean(record.category, body.details), ensure_ascii=False)
        if body.occurred_at is not None:
            record.occurred_at = _when(body.occurred_at)
        for f in session.scalars(select(RecordFile).where(RecordFile.record_id == record.id,
                                                          RecordFile.id.in_(body.remove_file_ids or [""]))):
            f.record_id = None  # back to the uploads; cleaned up later
            f.uploaded_by = staff.id
        session.flush()
        _attach(session, staff, record, body.add_file_ids)
        session.flush()
        if record.category == RecordCategory.DOCUMENT and not records.files_of(session, record.id):
            raise HTTPException(status_code=400, detail="A document needs its file.")
        record.version += 1
        record.updated_at = utcnow()
        records.publish(session, record, patient, session.get(Hospital, staff.hospital_id))
        audit(session, staff.hospital_id, staff.id, "record_corrected", "patient", patient.id,
              {"record_id": record.id, "version": record.version, "fields": sorted(changes)})
        session.flush()
        return _record_payload(session, record)


@router.post("/records/{record_id}/retract")
def retract_record(record_id: str, body: Retraction, staff: Staff = Depends(current_staff)) -> Dict[str, Any]:
    """Entered in error: kept here, marked retracted, and withdrawn from Endod."""
    with session_scope() as session:
        record = _record_for_update(session, staff, record_id)
        if record.retracted:
            raise HTTPException(status_code=409, detail="This record is already retracted.")
        records.retract(session, record, body.reason)
        audit(session, staff.hospital_id, staff.id, "record_retracted", "patient", record.patient_id,
              {"record_id": record.id, "reason": body.reason})
        session.flush()
        return _record_payload(session, record)


@router.get("/records/{record_id}/files/{file_id}")
def read_file(record_id: str, file_id: str, staff: Staff = Depends(readers)):
    with session_scope() as session:
        row = session.scalar(select(RecordFile).join(ClinicalRecord, ClinicalRecord.id == RecordFile.record_id).where(
            RecordFile.id == file_id, RecordFile.record_id == record_id,
            ClinicalRecord.hospital_id == staff.hospital_id))
        if row is None:
            raise HTTPException(status_code=404, detail="File not found.")
        audit(session, staff.hospital_id, staff.id, "record_file_viewed", "patient", row.patient_id,
              {"record_id": record_id, "file_id": file_id})
        return _send(row)


def _send(row: RecordFile) -> FileResponse:
    try:
        path = files.path_for(row.hospital_id, row.id)
    except files.FileRejected as exc:
        raise HTTPException(status_code=404, detail="File not found.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path, media_type=row.content_type, filename=row.filename, content_disposition_type="inline",
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
                                 "X-Sha256": row.sha256})


@platform_router.get("/platform/records/{record_id}/files/{file_id}", dependencies=[Depends(platform_admin)])
def platform_file(record_id: str, file_id: str):
    """For the Endod platform only (private network, X-Platform-Key): a file of
    a record published to Endod and not retracted."""
    with session_scope() as session:
        row = session.scalar(select(RecordFile).join(ClinicalRecord, ClinicalRecord.id == RecordFile.record_id).where(
            RecordFile.id == file_id, RecordFile.record_id == record_id,
            ClinicalRecord.published_dedan_id.is_not(None), ClinicalRecord.retracted.is_(False)))
        if row is None:
            raise HTTPException(status_code=404, detail="File not found.")
        return _send(row)


# --- visits and follow-ups -----------------------------------------------------------------------

class VisitCreate(BaseModel):
    #: A doctor opens their own visits; others name the doctor.
    doctor_id: OptionalText = Field(default=None, max_length=32)
    booking_id: OptionalText = Field(default=None, max_length=32)
    started_at: Optional[AwareDatetime] = None
    follow_up_on: Optional[date] = None
    follow_up_note: OptionalText = Field(default=None, max_length=500)


class FollowUp(BaseModel):
    #: null removes the follow-up (Endod is told it is cancelled).
    follow_up_on: Optional[date] = None
    follow_up_note: OptionalText = Field(default=None, max_length=500)


def _visit_payload(session, v: Visit) -> Dict[str, Any]:
    return {
        "id": v.id, "patient_id": v.patient_id, "booking_id": v.booking_id, "started_at": _iso(v.started_at),
        "doctor": {"id": v.doctor_id, "full_name": records.doctor_name(session, v)} if v.doctor_id else None,
        "follow_up_on": v.follow_up_on.isoformat() if v.follow_up_on else None,
        "follow_up_note": v.follow_up_note, "follow_up_sent": bool(v.follow_up_sent_to),
    }


def _check_follow_up(session, staff: Staff, on: Optional[date]) -> None:
    if on is None:
        return
    if staff.role not in FOLLOW_UP_SETTERS:
        raise HTTPException(status_code=403, detail="Only a doctor sets a follow-up.")
    today = records.hospital_today(session, staff.hospital_id)
    if on <= today or on > today + timedelta(days=730):
        raise HTTPException(status_code=400, detail="The follow-up must be after today and within two years.")


@router.get("/patients/{patient_id}/visits")
def list_visits(patient_id: str, staff: Staff = Depends(readers)) -> List[Dict[str, Any]]:
    with session_scope() as session:
        patient = _patient(session, staff, patient_id)
        rows = session.scalars(select(Visit).where(Visit.patient_id == patient.id).order_by(Visit.started_at.desc()))
        return [_visit_payload(session, v) for v in rows]


@router.post("/patients/{patient_id}/visits", status_code=status.HTTP_201_CREATED)
def create_visit(patient_id: str, body: VisitCreate,
                 staff: Staff = Depends(require_roles(*RECORD_WRITERS))) -> Dict[str, Any]:
    with session_scope() as session:
        patient = _patient(session, staff, patient_id, lock=True)
        doctor_id = body.doctor_id or (staff.id if staff.role == Role.DOCTOR else None)
        if doctor_id and session.scalar(select(StaffUser.id).where(
                StaffUser.id == doctor_id, StaffUser.hospital_id == staff.hospital_id,
                StaffUser.role == Role.DOCTOR)) is None:
            raise HTTPException(status_code=400, detail="Unknown doctor.")
        if body.booking_id and session.scalar(select(Booking.id).where(
                Booking.id == body.booking_id, Booking.hospital_id == staff.hospital_id)) is None:
            raise HTTPException(status_code=400, detail="Unknown booking.")
        _check_follow_up(session, staff, body.follow_up_on)
        visit = Visit(hospital_id=staff.hospital_id, patient_id=patient.id, doctor_id=doctor_id,
                      booking_id=body.booking_id, started_at=_when(body.started_at), created_by=staff.id)
        session.add(visit)
        session.flush()
        if body.follow_up_on:
            records.set_follow_up(session, visit, patient, session.get(Hospital, staff.hospital_id),
                                  body.follow_up_on, body.follow_up_note)
        audit(session, staff.hospital_id, staff.id, "visit_opened", "patient", patient.id, {"visit_id": visit.id})
        session.flush()
        return _visit_payload(session, visit)


@router.patch("/visits/{visit_id}")
def set_follow_up(visit_id: str, body: FollowUp,
                  staff: Staff = Depends(require_roles(*FOLLOW_UP_SETTERS))) -> Dict[str, Any]:
    with session_scope() as session:
        visit = session.scalar(select(Visit).where(Visit.id == visit_id, Visit.hospital_id == staff.hospital_id)
                               .with_for_update())
        if visit is None:
            raise HTTPException(status_code=404, detail="Visit not found.")
        _check_follow_up(session, staff, body.follow_up_on)
        if body.follow_up_on is None and visit.follow_up_on is None:
            raise HTTPException(status_code=400, detail="This visit has no follow-up.")
        patient = _patient(session, staff, visit.patient_id, lock=True)
        records.set_follow_up(session, visit, patient, session.get(Hospital, staff.hospital_id),
                              body.follow_up_on, body.follow_up_note)
        audit(session, staff.hospital_id, staff.id,
              "follow_up_set" if body.follow_up_on else "follow_up_cancelled", "patient", patient.id,
              {"visit_id": visit.id, "on": body.follow_up_on.isoformat() if body.follow_up_on else None})
        session.flush()
        return _visit_payload(session, visit)

