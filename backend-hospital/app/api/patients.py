"""Patient registration and the patient directory.

Every patient gets a hospital number (MRN) such as ``SPH-000124`` when
registered. Their Endod digital health ID (``dedan_id``) is set only once
Endod confirms the account (app/api/history.py, app/linking.py); an ID the
patient merely gives is kept as ``claimed_dedan_id`` until then.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.auth import Staff, audit, current_staff, require_roles
from app.db import ensure_aware, session_scope, utcnow
from app.models import (
    AlertKind, Department, DepartmentKind, Hospital, Patient, PatientAlert, PatientStatus, Payer, Role, Sex,
    StaffUser,
)
from app.validation import Name, OptionalDedanId, OptionalPhone, OptionalText, like_pattern, phone_digits

router = APIRouter(prefix="/patients", tags=["patients"])

#: Front desk and clinical staff register patients.
REGISTRARS = (Role.ADMIN, Role.RECEPTION, Role.RECORDS, Role.NURSE, Role.DOCTOR)
#: Who corrects identity, contact and payer details.
DEMOGRAPHIC_EDITORS = (Role.ADMIN, Role.RECEPTION, Role.RECORDS)
#: Who changes where the patient is in their care.
CLINICAL_EDITORS = (Role.ADMIN, Role.DOCTOR, Role.NURSE)

DEMOGRAPHIC_FIELDS = {
    "full_name", "full_name_am", "sex", "date_of_birth", "age_years", "phone", "address",
    "emergency_contact_name", "emergency_contact_phone", "payer", "payer_number", "claimed_dedan_id",
}
CLINICAL_FIELDS = {"status", "department_id", "ward_id", "bed", "attending_doctor_id", "diagnosis"}
#: Who sees the working diagnosis. Allergy and risk alerts are shown to everyone,
#: since they are safety information (the pharmacy and the cashier need them too).
DIAGNOSIS_READERS = (Role.ADMIN, Role.DOCTOR, Role.NURSE, Role.PHARMACIST, Role.RECORDS)
#: Identity fields whose old and new values go into the audit log.
TRACKED_FIELDS = ("full_name", "full_name_am", "sex", "date_of_birth", "phone", "claimed_dedan_id", "payer",
                  "payer_number")

# --- input ----------------------------------------------------------------------

class _Demographics(BaseModel):
    full_name_am: OptionalText = Field(default=None, max_length=120)
    date_of_birth: Optional[date] = None
    #: When the date of birth is not known; it is then estimated.
    age_years: Optional[int] = Field(default=None, ge=0, le=130)
    phone: OptionalPhone = None
    address: OptionalText = Field(default=None, max_length=200)
    emergency_contact_name: OptionalText = Field(default=None, max_length=120)
    emergency_contact_phone: OptionalPhone = None
    payer_number: OptionalText = Field(default=None, max_length=40)
    #: An Endod ID the patient gave: kept as a claim ("given, not yet linked")
    #: and never sent to Endod. The confirmed ``dedan_id`` is set only by
    #: linking (POST /patients/{id}/link) or by checking in an Endod booking.
    claimed_dedan_id: OptionalDedanId = None

    @model_validator(mode="before")
    @classmethod
    def _old_dedan_field(cls, data: Any) -> Any:
        # Older clients send the typed Endod ID as "dedan_id": it is a claim.
        if isinstance(data, dict) and "dedan_id" in data:
            data = dict(data)
            old = data.pop("dedan_id")
            data.setdefault("claimed_dedan_id", old)
        return data

    @model_validator(mode="after")
    def _one_birth_field(self):
        if self.date_of_birth is not None and self.age_years is not None:
            raise ValueError("give either date_of_birth or age_years, not both")
        return self


class PatientCreate(_Demographics):
    full_name: Name = Field(max_length=120)
    sex: str
    payer: str = Payer.CASH
    #: Register even though a patient with the same name and phone exists.
    confirm_duplicate: bool = False


class PatientUpdate(_Demographics):
    full_name: Optional[Name] = Field(default=None, max_length=120)
    sex: Optional[str] = None
    payer: Optional[str] = None
    status: Optional[str] = None
    department_id: OptionalText = Field(default=None, max_length=32)
    ward_id: OptionalText = Field(default=None, max_length=32)
    bed: OptionalText = Field(default=None, max_length=16)
    attending_doctor_id: OptionalText = Field(default=None, max_length=32)
    diagnosis: OptionalText = Field(default=None, max_length=200)


class AlertCreate(BaseModel):
    kind: str
    label: Name = Field(max_length=120)


def _one_of(name: str, value: Optional[str], allowed: Iterable[str]) -> None:
    allowed = tuple(allowed)
    if value is not None and value not in allowed:
        raise HTTPException(status_code=400, detail=f"{name} must be one of {list(allowed)}.")


# --- helpers --------------------------------------------------------------------

def _today(hospital: Hospital) -> date:
    return datetime.now(ZoneInfo(hospital.timezone)).date()


def _check_birth(born: Optional[date], today: date) -> None:
    # Against the hospital's date: a baby born just after midnight in Addis
    # Ababa is still "yesterday" on a UTC server.
    if born is not None and born > today:
        raise HTTPException(status_code=400, detail="date_of_birth cannot be in the future.")


def _age(born: Optional[date], today: date) -> Optional[int]:
    if born is None:
        return None
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _estimated_birth(age_years: int, today: date) -> date:
    # 1 January of the year that gives this age for the rest of the year.
    return date(today.year - age_years, 1, 1)


def _next_mrn(session, hospital_id: str) -> str:
    # The hospital row is locked, so two desks registering at once get
    # different numbers; the counter only ever goes up.
    hospital = session.scalar(select(Hospital).where(Hospital.id == hospital_id).with_for_update())
    hospital.mrn_counter += 1
    return f"{hospital.code}-{hospital.mrn_counter:06d}"


def _department(session, hospital_id: str, department_id: str, kinds: Iterable[str], label: str) -> Department:
    department = session.scalar(select(Department).where(
        Department.id == department_id, Department.hospital_id == hospital_id, Department.active.is_(True),
        Department.kind.in_(tuple(kinds))))
    if department is None:
        raise HTTPException(status_code=400, detail=f"Unknown {label}.")
    return department


def _doctor(session, hospital_id: str, doctor_id: str) -> StaffUser:
    doctor = session.scalar(select(StaffUser).where(
        StaffUser.id == doctor_id, StaffUser.hospital_id == hospital_id, StaffUser.role == Role.DOCTOR,
        StaffUser.active.is_(True)))
    if doctor is None:
        raise HTTPException(status_code=400, detail="Unknown doctor.")
    return doctor


def _payloads(session, patients: List[Patient], today: date, role: str, full: bool = True) -> List[Dict[str, Any]]:
    """Patients as the API shows them, with names of linked rows loaded in bulk.

    ``full=False`` is the directory row: no contact, address or payer details.
    Those come only with the full record, whose every opening is audited.
    """
    department_ids = {p.department_id for p in patients if p.department_id} | {p.ward_id for p in patients if p.ward_id}
    doctor_ids = {p.attending_doctor_id for p in patients if p.attending_doctor_id}
    departments = {d.id: d for d in session.scalars(select(Department).where(Department.id.in_(department_ids)))} \
        if department_ids else {}
    doctors = {u.id: u for u in session.scalars(select(StaffUser).where(StaffUser.id.in_(doctor_ids)))} \
        if doctor_ids else {}
    alerts: Dict[str, List[Dict[str, Any]]] = {}
    if patients:
        rows = session.scalars(select(PatientAlert).where(PatientAlert.patient_id.in_([p.id for p in patients]))
                               .order_by(PatientAlert.created_at))
        for alert in rows:
            alerts.setdefault(alert.patient_id, []).append({"id": alert.id, "kind": alert.kind, "label": alert.label})

    def place(department_id: Optional[str]) -> Optional[Dict[str, Any]]:
        d = departments.get(department_id) if department_id else None
        return {"id": d.id, "name": d.name, "name_am": d.name_am} if d else None

    out = []
    for p in patients:
        doctor = doctors.get(p.attending_doctor_id) if p.attending_doctor_id else None
        row = {
            "id": p.id,
            "mrn": p.mrn,
            "dedan_id": p.dedan_id,
            "claimed_dedan_id": p.claimed_dedan_id,
            "full_name": p.full_name,
            "full_name_am": p.full_name_am,
            "sex": p.sex,
            "age_years": _age(p.date_of_birth, today),
            "status": p.status,
            "department": place(p.department_id),
            "ward": place(p.ward_id),
            "bed": p.bed,
            "attending_doctor": {"id": doctor.id, "full_name": doctor.full_name} if doctor else None,
            "diagnosis": p.diagnosis if role in DIAGNOSIS_READERS else None,
            "alerts": alerts.get(p.id, []),
            "status_changed_at": ensure_aware(p.status_changed_at).isoformat() if p.status_changed_at else None,
        }
        if full:
            row.update({
                "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
                "dob_estimated": p.dob_estimated,
                "phone": p.phone,
                "address": p.address,
                "emergency_contact": {"name": p.emergency_contact_name, "phone": p.emergency_contact_phone},
                "payer": p.payer,
                "payer_number": p.payer_number,
                "created_at": ensure_aware(p.created_at).isoformat(),
            })
        out.append(row)
    return out


def _patient_for_update(session, hospital_id: str, patient_id: str) -> Patient:
    patient = session.scalar(select(Patient).where(
        Patient.id == patient_id, Patient.hospital_id == hospital_id).with_for_update())
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return patient


def _conflict(exc: IntegrityError) -> HTTPException:
    if "dedan_id" in str(exc.orig):
        return HTTPException(status_code=409, detail="This Endod ID is already linked to another patient.")
    return HTTPException(status_code=409, detail="The change conflicts with other data; reload and retry.")


# --- routes ---------------------------------------------------------------------

@router.get("")
def list_patients(
    q: Optional[str] = Query(default=None, max_length=120),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    department_id: Optional[str] = None,
    ward_id: Optional[str] = None,
    doctor_id: Optional[str] = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    staff: Staff = Depends(current_staff),
) -> Dict[str, Any]:
    """Search by name (English or Amharic), MRN, Endod ID or phone number.

    Rows leave out contact and payer details; a search by name or number is
    audited, since it can find a specific person.
    """
    _one_of("status", status_filter, PatientStatus.ALL)
    query = select(Patient).where(Patient.hospital_id == staff.hospital_id)
    if status_filter:
        query = query.where(Patient.status == status_filter)
    if department_id:
        query = query.where(Patient.department_id == department_id)
    if ward_id:
        query = query.where(Patient.ward_id == ward_id)
    if doctor_id:
        query = query.where(Patient.attending_doctor_id == doctor_id)
    if q and q.strip():
        term = q.strip()
        matches = [func.lower(Patient.full_name).like(like_pattern(term.lower()), escape="\\"),
                   Patient.full_name_am.like(like_pattern(term), escape="\\"),
                   Patient.mrn.like(like_pattern(term.upper()), escape="\\"),
                   Patient.dedan_id.like(like_pattern(term.upper()), escape="\\"),
                   # Endod IDs are stored as DE482731; staff also type DE-482731.
                   Patient.dedan_id.like(like_pattern(re.sub(r"[\s-]", "", term.upper())), escape="\\"),
                   # An ID given but not yet confirmed finds the patient too.
                   Patient.claimed_dedan_id.like(like_pattern(term.upper()), escape="\\"),
                   Patient.claimed_dedan_id.like(like_pattern(re.sub(r"[\s-]", "", term.upper())), escape="\\")]
        digits = phone_digits(term)
        if digits:
            matches.append(Patient.phone.like(like_pattern(digits), escape="\\"))
        query = query.where(or_(*matches))
    with session_scope(staff.hospital_id) as session:
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        patients = list(session.scalars(
            query.order_by(Patient.created_at.desc(), Patient.mrn.desc()).limit(limit).offset(offset)))
        hospital = session.get(Hospital, staff.hospital_id)
        if q and q.strip():
            audit(session, staff.hospital_id, staff.id, "patients_searched", "patient", None,
                  {"q": q.strip(), "results": [p.id for p in patients]})
        return {"items": _payloads(session, patients, _today(hospital), staff.role, full=False), "total": total,
                "limit": limit, "offset": offset}


@router.get("/stats")
def patient_stats(staff: Staff = Depends(current_staff)) -> Dict[str, Any]:
    """Counts for the directory's summary cards and tabs."""
    with session_scope(staff.hospital_id) as session:
        hospital = session.get(Hospital, staff.hospital_id)
        by_status = dict(session.execute(
            select(Patient.status, func.count()).where(Patient.hospital_id == staff.hospital_id)
            .group_by(Patient.status)).all())
        midnight = datetime.combine(_today(hospital), time.min, ZoneInfo(hospital.timezone)).astimezone(timezone.utc)
        today = session.scalar(select(func.count()).where(
            Patient.hospital_id == staff.hospital_id, Patient.created_at >= midnight)) or 0
        return {
            "total": sum(by_status.values()),
            "registered_today": today,
            "by_status": {key: by_status.get(key, 0) for key in PatientStatus.ALL},
        }


@router.post("", status_code=status.HTTP_201_CREATED)
def register_patient(body: PatientCreate, staff: Staff = Depends(require_roles(*REGISTRARS))) -> Dict[str, Any]:
    _one_of("sex", body.sex, Sex.ALL)
    _one_of("payer", body.payer, Payer.ALL)
    try:
        with session_scope(staff.hospital_id) as session:
            hospital = session.get(Hospital, staff.hospital_id)
            today = _today(hospital)
            _check_birth(body.date_of_birth, today)
            # Taking the number locks the hospital row first, so two desks
            # registering the same person cannot both pass the duplicate check.
            mrn = _next_mrn(session, staff.hospital_id)
            if body.phone and not body.confirm_duplicate:
                existing = session.scalar(select(Patient).where(
                    Patient.hospital_id == staff.hospital_id, Patient.phone == body.phone,
                    func.lower(Patient.full_name) == body.full_name.lower()))
                if existing is not None:
                    raise HTTPException(status_code=409, detail=(
                        f"{existing.full_name} with this phone number is already registered as {existing.mrn}. "
                        "Open that record, or register again with confirm_duplicate set."))
            born, estimated = body.date_of_birth, False
            if born is None and body.age_years is not None:
                born, estimated = _estimated_birth(body.age_years, today), True
            patient = Patient(
                hospital_id=staff.hospital_id, mrn=mrn,
                full_name=body.full_name, full_name_am=body.full_name_am, sex=body.sex, date_of_birth=born,
                dob_estimated=estimated, phone=body.phone, address=body.address,
                emergency_contact_name=body.emergency_contact_name,
                emergency_contact_phone=body.emergency_contact_phone, payer=body.payer,
                payer_number=body.payer_number, claimed_dedan_id=body.claimed_dedan_id,
                status=PatientStatus.OPD, status_changed_at=utcnow(),
                created_by=staff.id,
            )
            session.add(patient)
            session.flush()
            audit(session, staff.hospital_id, staff.id, "patient_registered", "patient", patient.id,
                  {"mrn": patient.mrn})
            return _payloads(session, [patient], today, staff.role)[0]
    except IntegrityError as exc:
        raise _conflict(exc) from exc


@router.get("/{patient_id}")
def read_patient(patient_id: str, staff: Staff = Depends(current_staff)) -> Dict[str, Any]:
    with session_scope(staff.hospital_id) as session:
        patient = session.scalar(select(Patient).where(
            Patient.id == patient_id, Patient.hospital_id == staff.hospital_id))
        if patient is None:
            raise HTTPException(status_code=404, detail="Patient not found.")
        # Opening a record is logged: who looked at which patient, and when.
        audit(session, staff.hospital_id, staff.id, "patient_viewed", "patient", patient.id)
        return _payloads(session, [patient], _today(session.get(Hospital, staff.hospital_id)), staff.role)[0]


@router.patch("/{patient_id}")
def update_patient(patient_id: str, body: PatientUpdate, staff: Staff = Depends(current_staff)) -> Dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    # Required fields cannot be cleared, and an age of null means nothing.
    for field in ("full_name", "sex", "payer", "status", "age_years"):
        if field in changes and changes[field] is None:
            changes.pop(field)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    if DEMOGRAPHIC_FIELDS & changes.keys() and staff.role not in DEMOGRAPHIC_EDITORS:
        raise HTTPException(status_code=403, detail="Only registration staff change patient details.")
    if CLINICAL_FIELDS & changes.keys() and staff.role not in CLINICAL_EDITORS:
        raise HTTPException(status_code=403, detail="Only clinical staff change a patient's care status.")
    _one_of("sex", changes.get("sex"), Sex.ALL)
    _one_of("payer", changes.get("payer"), Payer.ALL)
    _one_of("status", changes.get("status"), PatientStatus.ALL)

    try:
        with session_scope(staff.hospital_id) as session:
            patient = _patient_for_update(session, staff.hospital_id, patient_id)
            hospital = session.get(Hospital, staff.hospital_id)
            today = _today(hospital)

            if "age_years" in changes:
                changes["date_of_birth"] = _estimated_birth(changes.pop("age_years"), today)
                changes["dob_estimated"] = True
            elif "date_of_birth" in changes:
                _check_birth(changes["date_of_birth"], today)
                changes["dob_estimated"] = False
            if changes.get("department_id"):
                _department(session, staff.hospital_id, changes["department_id"],
                            (DepartmentKind.DEPARTMENT, DepartmentKind.CLINIC), "department")
            if changes.get("attending_doctor_id"):
                _doctor(session, staff.hospital_id, changes["attending_doctor_id"])

            old_status, old_ward, old_bed = patient.status, patient.ward_id, patient.bed
            new_status = changes.get("status", old_status)
            if new_status in PatientStatus.IN_BED:
                ward_id = changes.get("ward_id", old_ward)
                if ward_id != old_ward and "bed" not in changes:
                    # A bed number belongs to its ward; a move without one leaves it open.
                    changes["bed"] = None
                bed = changes.get("bed", old_bed)
                if not ward_id:
                    raise HTTPException(status_code=400, detail="Choose a ward for an admitted patient.")
                if ward_id != old_ward or bed != old_bed or old_status not in PatientStatus.IN_BED:
                    _take_bed(session, staff.hospital_id, patient, ward_id, bed)
            else:
                if changes.get("ward_id") or changes.get("bed"):
                    raise HTTPException(status_code=400, detail="Only an admitted patient has a ward and bed.")
                # Leaving the ward frees the bed.
                changes["ward_id"] = None
                changes["bed"] = None

            before = {f: getattr(patient, f) for f in TRACKED_FIELDS if f in changes}
            for field, value in changes.items():
                setattr(patient, field, value)
            if new_status != old_status:
                patient.status_changed_at = utcnow()
                audit(session, staff.hospital_id, staff.id, "patient_status_changed", "patient", patient.id,
                      {"from": old_status, "to": new_status})
            # Identity changes keep the old value, so a wrong edit (or an unlinked
            # Endod ID) can be traced and undone.
            identity = {f: {"from": _plain(v), "to": _plain(getattr(patient, f))}
                        for f, v in before.items() if v != getattr(patient, f)}
            audit(session, staff.hospital_id, staff.id, "patient_updated", "patient", patient.id,
                  {"fields": sorted(changes), **({"identity": identity} if identity else {})})
            session.flush()
            return _payloads(session, [patient], today, staff.role)[0]
    except IntegrityError as exc:
        raise _conflict(exc) from exc


def _plain(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def _take_bed(session, hospital_id: str, patient: Patient, ward_id: str, bed: Optional[str]) -> None:
    """Check the ward has room and the bed is free. The ward row is locked,
    so two admissions to the same ward are decided one after the other."""
    ward = session.scalar(select(Department).where(
        Department.id == ward_id, Department.hospital_id == hospital_id, Department.active.is_(True),
        Department.kind == DepartmentKind.WARD).with_for_update())
    if ward is None:
        raise HTTPException(status_code=400, detail="Unknown ward.")
    others = select(Patient).where(Patient.ward_id == ward.id, Patient.status.in_(PatientStatus.IN_BED),
                                   Patient.id != patient.id)
    if bed and session.scalar(others.where(Patient.bed == bed)) is not None:
        raise HTTPException(status_code=409, detail=f"Bed {bed} in {ward.name} is taken.")
    moving_in = patient.ward_id != ward.id or patient.status not in PatientStatus.IN_BED
    if moving_in and ward.capacity is not None:
        occupied = session.scalar(select(func.count()).select_from(others.subquery())) or 0
        if occupied >= ward.capacity:
            raise HTTPException(status_code=409, detail=f"{ward.name} is full ({ward.capacity} beds).")


@router.post("/{patient_id}/alerts", status_code=status.HTTP_201_CREATED)
def add_alert(patient_id: str, body: AlertCreate,
              staff: Staff = Depends(require_roles(*CLINICAL_EDITORS))) -> Dict[str, Any]:
    _one_of("kind", body.kind, AlertKind.ALL)
    with session_scope(staff.hospital_id) as session:
        patient = _patient_for_update(session, staff.hospital_id, patient_id)
        alert = PatientAlert(hospital_id=patient.hospital_id, patient_id=patient.id, kind=body.kind,
                             label=body.label, created_by=staff.id)
        session.add(alert)
        session.flush()
        audit(session, staff.hospital_id, staff.id, "patient_alert_added", "patient", patient.id,
              {"kind": body.kind, "label": body.label})
        return {"id": alert.id, "kind": alert.kind, "label": alert.label}


@router.delete("/{patient_id}/alerts/{alert_id}")
def remove_alert(patient_id: str, alert_id: str,
                 staff: Staff = Depends(require_roles(*CLINICAL_EDITORS))) -> Dict[str, Any]:
    with session_scope(staff.hospital_id) as session:
        patient = _patient_for_update(session, staff.hospital_id, patient_id)
        alert = session.scalar(select(PatientAlert).where(
            PatientAlert.id == alert_id, PatientAlert.patient_id == patient.id))
        if alert is None:
            raise HTTPException(status_code=404, detail="Alert not found.")
        session.delete(alert)
        audit(session, staff.hospital_id, staff.id, "patient_alert_removed", "patient", patient.id,
              {"kind": alert.kind, "label": alert.label})
        return {"ok": True}
