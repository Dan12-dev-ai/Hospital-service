"""Clinical records, visits and follow-ups, and what Endod is told about them.

A record is published to the patient platform (``record.published``) only
for a patient linked to Endod; a correction is published again with a
higher ``version``; a retraction is sent as ``record.retracted``. A visit's
follow-up is sent as ``visit.follow_up`` (``cancelled`` when removed). The
contract is docs/history-events.md, sections 2 and 3.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import eventbus
from app.db import ensure_aware, utcnow
from app.models import ClinicalRecord, Hospital, Patient, RecordCategory, RecordFile, StaffUser, Visit


def _text(value: Any) -> Any:
    """Numbers are kept as text (a dose of 500, a value of 5.4); "" is no value."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip() or None
    return value


def _required_text(value: Any) -> Any:
    value = _text(value)
    if value is None:
        raise ValueError("this field is required")
    return value


def T(max_length: int):  # noqa: N802 -- a short type factory
    """Optional text of at most ``max_length`` characters (null and "" are no value)."""
    return Annotated[Optional[Annotated[str, StringConstraints(max_length=max_length)]], BeforeValidator(_text),
                     Field(default=None)]


def Required(max_length: int):  # noqa: N802
    return Annotated[Annotated[str, StringConstraints(min_length=1, max_length=max_length)],
                     BeforeValidator(_required_text)]


class _Details(BaseModel):
    #: Unknown keys are ignored (the contract allows them).
    model_config = ConfigDict(extra="ignore")


class Diagnosis(_Details):
    condition: Required(200)
    code: T(16)
    status: Literal["active", "resolved", "chronic"] = "active"
    notes: T(2000)


class PrescriptionItem(_Details):
    drug: Required(120)
    dose: T(60)
    route: T(40)
    frequency: T(60)
    duration: T(60)
    quantity: T(40)
    notes: T(300)


class Prescription(_Details):
    items: List[PrescriptionItem] = Field(min_length=1, max_length=30)
    notes: T(2000)


class LabItem(_Details):
    test: Required(120)
    value: T(60)
    unit: T(30)
    reference_range: T(60)
    flag: Optional[Literal["low", "normal", "high", "critical"]] = None


class LabResult(_Details):
    items: List[LabItem] = Field(min_length=1, max_length=60)
    specimen: T(60)
    notes: T(2000)


class Imaging(_Details):
    modality: Required(60)
    body_part: T(80)
    findings: T(4000)
    impression: T(2000)


class Vitals(_Details):
    bp: T(20)
    pulse: T(10)
    temp: T(10)
    weight: T(10)
    height: T(10)
    spo2: T(10)


class VisitNote(_Details):
    complaint: T(1000)
    findings: T(4000)
    plan: T(2000)
    vitals: Annotated[Vitals, BeforeValidator(lambda v: {} if v is None else v)] = Field(default_factory=Vitals)


class Document(_Details):
    description: T(1000)


DETAILS = {
    RecordCategory.DIAGNOSIS: Diagnosis,
    RecordCategory.PRESCRIPTION: Prescription,
    RecordCategory.LAB_RESULT: LabResult,
    RecordCategory.IMAGING: Imaging,
    RecordCategory.VISIT_NOTE: VisitNote,
    RecordCategory.DOCUMENT: Document,
}


class DetailsError(ValueError):
    pass


def clean_details(category: str, details: Union[Dict[str, Any], None]) -> Dict[str, Any]:
    """The category's details, checked, with unknown keys dropped. Raises DetailsError."""
    model = DETAILS.get(category)
    if model is None:
        raise DetailsError(f"category must be one of {list(RecordCategory.ALL)}")
    try:
        cleaned = model.model_validate(details or {}).model_dump()
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ())) or "details"
        raise DetailsError(f"details.{where}: {first.get('msg')}") from exc
    if category == RecordCategory.VISIT_NOTE and not any(
            [cleaned["complaint"], cleaned["findings"], cleaned["plan"], *cleaned["vitals"].values()]):
        raise DetailsError("details: a visit note needs a complaint, findings, a plan or vitals")
    return cleaned


#: Each category's details for :func:`salvage_details`: a field's longest text,
#: its allowed values, or (for ``items`` and ``vitals``) the fields of its objects.
#: The same shape as the models above (a test keeps them in step).
_FLAGS = ("low", "normal", "high", "critical")
SALVAGE: Dict[str, Dict[str, Any]] = {
    RecordCategory.DIAGNOSIS: {"condition": 200, "code": 16, "status": ("active", "resolved", "chronic"),
                               "notes": 2000},
    RecordCategory.PRESCRIPTION: {"items": {"drug": 120, "dose": 60, "route": 40, "frequency": 60, "duration": 60,
                                            "quantity": 40, "notes": 300}, "notes": 2000},
    RecordCategory.LAB_RESULT: {"items": {"test": 120, "value": 60, "unit": 30, "reference_range": 60,
                                          "flag": _FLAGS}, "specimen": 60, "notes": 2000},
    RecordCategory.IMAGING: {"modality": 60, "body_part": 80, "findings": 4000, "impression": 2000},
    RecordCategory.VISIT_NOTE: {"complaint": 1000, "findings": 4000, "plan": 2000,
                                "vitals": {"bp": 20, "pulse": 10, "temp": 10, "weight": 10, "height": 10, "spo2": 10}},
    RecordCategory.DOCUMENT: {"description": 1000},
}
_MAX_ITEMS = 60


def _salvage(spec: Dict[str, Any], data: Any) -> Dict[str, Any]:
    data = data if isinstance(data, dict) else {}
    out: Dict[str, Any] = {}
    for key, rule in spec.items():
        value = data.get(key)
        if isinstance(rule, int):
            value = _text(value)
            out[key] = value[:rule] if isinstance(value, str) else None
        elif isinstance(rule, tuple):
            out[key] = value if value in rule else None
        elif key == "items":
            rows = [_salvage(rule, item) for item in value if isinstance(item, dict)] \
                if isinstance(value, list) else []
            out[key] = [row for row in rows if any(v is not None for v in row.values())][:_MAX_ITEMS]
        else:
            out[key] = _salvage(rule, value)
    return out


def salvage_details(category: str, details: Any) -> Dict[str, Any]:
    """What can be kept of details that fail :func:`clean_details` (a patient's
    sparse self-reported record): the known fields only, as text clipped to
    their length; values outside a field's choices, and list items that are
    not objects (null, numbers, strings) or are empty, are dropped. Never raw."""
    spec = SALVAGE.get(category)
    return _salvage(spec, details) if spec is not None else {}


def hospital_today(session: Session, hospital_id: str) -> date:
    """Today's date where the hospital is (not on the server's clock)."""
    return datetime.now(ZoneInfo(session.get(Hospital, hospital_id).timezone)).date()


def iso(value: datetime) -> str:
    return ensure_aware(value).astimezone(timezone.utc).isoformat()


def file_payload(f: RecordFile) -> Dict[str, Any]:
    return {"file_id": f.id, "filename": f.filename, "content_type": f.content_type, "size": f.size,
            "sha256": f.sha256}


def files_of(session: Session, record_id: str) -> List[RecordFile]:
    return list(session.scalars(select(RecordFile).where(RecordFile.record_id == record_id)
                                .order_by(RecordFile.created_at, RecordFile.id)))


# --- publishing -------------------------------------------------------------------

def publish(session: Session, record: ClinicalRecord, patient: Patient, hospital: Hospital) -> bool:
    """Tell Endod the record's current version, if the patient is linked. Returns
    whether it was sent."""
    if record.retracted:
        return False
    dedan = patient.dedan_id
    if dedan and record.published_dedan_id and record.published_dedan_id != dedan:
        # The patient was re-linked to another account: take it off the old one.
        retract_from_platform(session, record, record.published_dedan_id,
                              "The hospital linked this record to a different Endod account.")
    if not dedan:
        return False
    eventbus.emit(session, "record.published", {
        "record_id": record.id,
        "version": record.version,
        "hospital_id": hospital.id,
        "hospital_name": hospital.name,
        "dedan_id": dedan,
        "visit_id": record.visit_id,
        "category": record.category,
        "title": record.title,
        "details": json.loads(record.details),
        "occurred_at": iso(record.occurred_at),
        "recorded_by": record.recorded_by_name,
        "source": record.source,
        "files": [file_payload(f) for f in files_of(session, record.id)],
    })
    record.published_dedan_id = dedan
    record.published_version = record.version
    return True


def needs_publishing(record: ClinicalRecord, dedan_id: Optional[str]) -> bool:
    """Whether Endod lacks this record's current version for the account
    ``dedan_id``: never sent there, sent to another account, or corrected
    since (for instance while the patient was unlinked)."""
    if record.retracted or not dedan_id:
        return False
    return record.published_dedan_id != dedan_id or (record.published_version or 0) < record.version


def retract_from_platform(session: Session, record: ClinicalRecord, dedan_id: str, reason: str) -> None:
    eventbus.emit(session, "record.retracted", {
        "record_id": record.id, "hospital_id": record.hospital_id, "dedan_id": dedan_id, "reason": reason,
    })
    record.published_dedan_id = None
    record.published_version = None


def retract(session: Session, record: ClinicalRecord, reason: str) -> None:
    record.retracted = True
    record.retracted_reason = reason
    record.retracted_at = utcnow()
    # Entered in error: the same source item may be imported again.
    record.import_key = None
    if record.published_dedan_id:
        dedan = record.published_dedan_id
        retract_from_platform(session, record, dedan, reason)
        # Remember where it was, for the record's own history.
        record.published_dedan_id = dedan


def doctor_name(session: Session, visit: Visit) -> Optional[str]:
    if not visit.doctor_id:
        return None
    doctor = session.get(StaffUser, visit.doctor_id)
    return doctor.full_name if doctor else None


def _follow_up_event(session: Session, visit: Visit, hospital: Hospital, dedan_id: str, on: date,
                     note: Optional[str], cancelled: bool) -> None:
    eventbus.emit(session, "visit.follow_up", {
        "visit_id": visit.id, "hospital_id": hospital.id, "hospital_name": hospital.name,
        "dedan_id": dedan_id, "follow_up_on": on.isoformat(), "note": note,
        "doctor_name": doctor_name(session, visit), "cancelled": cancelled,
    })


def set_follow_up(session: Session, visit: Visit, patient: Patient, hospital: Hospital,
                  on: Optional[date], note: Optional[str]) -> None:
    """Set, move or remove a visit's follow-up, and tell Endod."""
    old_on, sent_to = visit.follow_up_on, visit.follow_up_sent_to
    visit.follow_up_on, visit.follow_up_note = on, (note if on else None)
    if sent_to and old_on and (on is None or sent_to != patient.dedan_id):
        _follow_up_event(session, visit, hospital, sent_to, old_on, None, cancelled=True)
        visit.follow_up_sent_to = None
    if on and patient.dedan_id:
        _follow_up_event(session, visit, hospital, patient.dedan_id, on, visit.follow_up_note, cancelled=False)
        visit.follow_up_sent_to = patient.dedan_id


def publish_history(session: Session, patient: Patient, today: date) -> int:
    """A patient was just linked: send their records (each one Endod does not
    have in its current version, including corrections made while unlinked)
    and upcoming follow-ups. Returns how many records were sent."""
    hospital = session.get(Hospital, patient.hospital_id)
    sent = 0
    for record in session.scalars(select(ClinicalRecord).where(
            ClinicalRecord.patient_id == patient.id, ClinicalRecord.retracted.is_(False))
            .order_by(ClinicalRecord.occurred_at)):
        if needs_publishing(record, patient.dedan_id):
            sent += publish(session, record, patient, hospital)
    for visit in session.scalars(select(Visit).where(Visit.patient_id == patient.id,
                                                     Visit.follow_up_on.is_not(None),
                                                     Visit.follow_up_on >= today)):
        if visit.follow_up_sent_to != patient.dedan_id:
            set_follow_up(session, visit, patient, hospital, visit.follow_up_on, visit.follow_up_note)
    return sent
