"""The doctors directory: who is on duty, where, and how busy.

A doctor is a staff account with the doctor role; ``DoctorProfile`` holds
the directory details (licence, specialty, rank, duty status).
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.auth import Staff, audit, current_staff, require_roles
from app.db import ensure_aware, session_scope, utcnow
from app.models import (
    Department, DoctorProfile, DoctorRank, DutyStatus, Hospital, Patient, PatientStatus, Role, StaffUser,
)
from app.validation import OptionalText, like_pattern, phone_digits

router = APIRouter(prefix="/doctors", tags=["doctors"])

#: Patients in a bed or in the emergency bay count toward a doctor's load
#: until they leave; outpatients count on the day they were seen.
_ONGOING_CARE = (PatientStatus.EMERGENCY, PatientStatus.ADMITTED, PatientStatus.DISCHARGE)


class ProfileUpdate(BaseModel):
    license_number: OptionalText = Field(default=None, max_length=40)
    credentials: OptionalText = Field(default=None, max_length=80)
    specialty: OptionalText = Field(default=None, max_length=120)
    rank: OptionalText = None
    extension: OptionalText = Field(default=None, max_length=16)
    daily_capacity: Optional[int] = Field(default=None, ge=1, le=500)


class DutyUpdate(BaseModel):
    duty_status: str
    duty_location: OptionalText = Field(default=None, max_length=60)


def _load(session, hospital_id: str, doctor_ids: List[str]) -> Dict[str, int]:
    if not doctor_ids:
        return {}
    hospital = session.get(Hospital, hospital_id)
    zone = ZoneInfo(hospital.timezone)
    midnight = datetime.combine(datetime.now(zone).date(), time.min, zone).astimezone(timezone.utc)
    return dict(session.execute(
        select(Patient.attending_doctor_id, func.count())
        .where(Patient.attending_doctor_id.in_(doctor_ids), or_(
            Patient.status.in_(_ONGOING_CARE),
            (Patient.status == PatientStatus.OPD) & (Patient.status_changed_at >= midnight)))
        .group_by(Patient.attending_doctor_id)).all())


def _payload(user: StaffUser, profile: Optional[DoctorProfile], department: Optional[Department],
             patients: int) -> Dict[str, Any]:
    capacity = profile.daily_capacity if profile else None
    return {
        "id": user.id,
        "full_name": user.full_name,
        "full_name_am": user.full_name_am,
        "email": user.email,
        "phone": user.phone,
        "active": user.active,
        "department": {"id": department.id, "name": department.name, "name_am": department.name_am}
        if department else None,
        "license_number": profile.license_number if profile else None,
        "credentials": profile.credentials if profile else None,
        "specialty": profile.specialty if profile else None,
        "rank": profile.rank if profile else None,
        "extension": profile.extension if profile else None,
        "duty_status": profile.duty_status if profile else DutyStatus.OFF_DUTY,
        "duty_location": profile.duty_location if profile else None,
        "duty_updated_at": ensure_aware(profile.duty_updated_at).isoformat()
        if profile and profile.duty_updated_at else None,
        "load": {
            "patients": patients,
            "capacity": capacity,
            "percent": min(100, round(100 * patients / capacity)) if capacity else None,
        },
    }


def _rows(session, query) -> List[Tuple[StaffUser, Optional[DoctorProfile], Optional[Department]]]:
    return [tuple(row) for row in session.execute(query)]


def _base_query(hospital_id: str):
    return (
        select(StaffUser, DoctorProfile, Department)
        .outerjoin(DoctorProfile, DoctorProfile.user_id == StaffUser.id)
        .outerjoin(Department, Department.id == StaffUser.department_id)
        .where(StaffUser.hospital_id == hospital_id, StaffUser.role == Role.DOCTOR)
    )


def _doctor_for_update(session, hospital_id: str, doctor_id: str) -> Tuple[StaffUser, DoctorProfile]:
    # The staff row is locked, so two first edits cannot both create the profile.
    user = session.scalar(select(StaffUser).where(
        StaffUser.id == doctor_id, StaffUser.hospital_id == hospital_id, StaffUser.role == Role.DOCTOR)
        .with_for_update())
    if user is None:
        raise HTTPException(status_code=404, detail="Doctor not found.")
    profile = session.scalar(select(DoctorProfile).where(DoctorProfile.user_id == user.id))
    if profile is None:
        profile = DoctorProfile(user_id=user.id, hospital_id=hospital_id, duty_status=DutyStatus.OFF_DUTY)
        session.add(profile)
    return user, profile


def _read_one(session, hospital_id: str, doctor_id: str) -> Dict[str, Any]:
    row = session.execute(_base_query(hospital_id).where(StaffUser.id == doctor_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Doctor not found.")
    user, profile, department = row
    return _payload(user, profile, department, _load(session, hospital_id, [user.id]).get(user.id, 0))


@router.get("")
def list_doctors(
    q: Optional[str] = Query(default=None, max_length=120),
    department_id: Optional[str] = None,
    rank: Optional[str] = None,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    include_inactive: bool = False,
    staff: Staff = Depends(current_staff),
) -> Dict[str, Any]:
    """The directory, with how many doctors are in each duty status (for the tabs).

    The counts follow every filter except ``status``.
    """
    if status_filter is not None and status_filter not in DutyStatus.ALL:
        raise HTTPException(status_code=400, detail=f"status must be one of {list(DutyStatus.ALL)}.")
    if rank is not None and rank not in DoctorRank.ALL:
        raise HTTPException(status_code=400, detail=f"rank must be one of {list(DoctorRank.ALL)}.")
    query = _base_query(staff.hospital_id)
    if not include_inactive:
        query = query.where(StaffUser.active.is_(True))
    if department_id:
        query = query.where(StaffUser.department_id == department_id)
    if rank:
        query = query.where(DoctorProfile.rank == rank)
    if q and q.strip():
        term = q.strip()
        like = like_pattern(term.lower())
        matches = [
            func.lower(StaffUser.full_name).like(like, escape="\\"),
            StaffUser.full_name_am.like(like_pattern(term), escape="\\"),
            func.lower(DoctorProfile.license_number).like(like, escape="\\"),
            func.lower(DoctorProfile.specialty).like(like, escape="\\"),
            func.lower(Department.name).like(like, escape="\\"),
            DoctorProfile.extension.like(like, escape="\\"),
        ]
        digits = phone_digits(term)
        if digits:
            matches.append(StaffUser.phone.like(like_pattern(digits), escape="\\"))
        query = query.where(or_(*matches))
    with session_scope() as session:
        rows = _rows(session, query.order_by(StaffUser.full_name))
        counts = {key: 0 for key in DutyStatus.ALL}
        for _, profile, _ in rows:
            counts[profile.duty_status if profile else DutyStatus.OFF_DUTY] += 1
        if status_filter:
            rows = [r for r in rows if (r[1].duty_status if r[1] else DutyStatus.OFF_DUTY) == status_filter]
        load = _load(session, staff.hospital_id, [user.id for user, _, _ in rows])
        return {
            "items": [_payload(user, profile, department, load.get(user.id, 0)) for user, profile, department in rows],
            "counts": {"all": sum(counts.values()), **counts},
        }


@router.get("/{doctor_id}")
def read_doctor(doctor_id: str, staff: Staff = Depends(current_staff)) -> Dict[str, Any]:
    with session_scope() as session:
        return _read_one(session, staff.hospital_id, doctor_id)


@router.patch("/{doctor_id}/profile")
def update_profile(doctor_id: str, body: ProfileUpdate,
                   staff: Staff = Depends(require_roles(Role.ADMIN))) -> Dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if changes.get("rank") is not None and changes["rank"] not in DoctorRank.ALL:
        raise HTTPException(status_code=400, detail=f"rank must be one of {list(DoctorRank.ALL)}.")
    try:
        with session_scope() as session:
            _, profile = _doctor_for_update(session, staff.hospital_id, doctor_id)
            for field, value in changes.items():
                setattr(profile, field, value)
            audit(session, staff.hospital_id, staff.id, "doctor_profile_updated", "staff", doctor_id,
                  {"fields": sorted(changes)})
            session.flush()
            return _read_one(session, staff.hospital_id, doctor_id)
    except IntegrityError as exc:
        if "license" in str(exc.orig):
            raise HTTPException(status_code=409, detail="Another doctor here has this licence number.") from exc
        raise HTTPException(status_code=409, detail="The change conflicts with other data; reload and retry.") from exc


@router.patch("/{doctor_id}/duty")
def update_duty(doctor_id: str, body: DutyUpdate, staff: Staff = Depends(current_staff)) -> Dict[str, Any]:
    """A doctor sets their own duty status; admins and nurses (the duty desk) can set anyone's."""
    if staff.id != doctor_id and staff.role not in (Role.ADMIN, Role.NURSE):
        raise HTTPException(status_code=403, detail="You can only change your own duty status.")
    if body.duty_status not in DutyStatus.ALL:
        raise HTTPException(status_code=400, detail=f"duty_status must be one of {list(DutyStatus.ALL)}.")
    with session_scope() as session:
        user, profile = _doctor_for_update(session, staff.hospital_id, doctor_id)
        if not user.active:
            raise HTTPException(status_code=400, detail="This account is deactivated.")
        profile.duty_status = body.duty_status
        profile.duty_location = None if body.duty_status == DutyStatus.OFF_DUTY else body.duty_location
        profile.duty_updated_at = utcnow()
        audit(session, staff.hospital_id, staff.id, "doctor_duty_changed", "staff", doctor_id,
              {"status": body.duty_status})
        session.flush()
        return _read_one(session, staff.hospital_id, doctor_id)
