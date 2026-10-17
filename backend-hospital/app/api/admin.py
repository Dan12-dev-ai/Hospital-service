"""Hospital settings, departments and staff accounts (admins only, except reads)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app import auth
from app.auth import Staff, audit, current_staff, require_roles, staff_payload
from app.db import session_scope
from app.models import Department, DepartmentKind, Hospital, Role, StaffUser
from app.security import hash_password, temporary_password
from app.validation import Name, OptionalPhone, OptionalText

router = APIRouter(tags=["administration"])
admin_only = require_roles(Role.ADMIN)


# --- hospital -----------------------------------------------------------------

def hospital_payload(h: Hospital) -> Dict[str, Any]:
    return {"id": h.id, "code": h.code, "name": h.name, "name_am": h.name_am, "timezone": h.timezone,
            "directory_facility_id": h.directory_facility_id}


class HospitalUpdate(BaseModel):
    name: Optional[Name] = Field(default=None, max_length=160)
    name_am: OptionalText = Field(default=None, max_length=160)
    timezone: Optional[str] = Field(default=None, max_length=64)


@router.get("/hospital")
def read_hospital(staff: Staff = Depends(current_staff)) -> Dict[str, Any]:
    with session_scope() as session:
        return hospital_payload(session.get(Hospital, staff.hospital_id))


@router.patch("/hospital")
def update_hospital(body: HospitalUpdate, staff: Staff = Depends(admin_only)) -> Dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"] or "")
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Unknown timezone.") from exc
    if changes.get("name") is None:
        changes.pop("name", None)
    with session_scope() as session:
        hospital = session.get(Hospital, staff.hospital_id)
        for field, value in changes.items():
            setattr(hospital, field, value)
        audit(session, staff.hospital_id, staff.id, "hospital_updated", detail={"fields": sorted(changes)})
        return hospital_payload(hospital)


# --- departments --------------------------------------------------------------

def department_payload(d: Department) -> Dict[str, Any]:
    return {"id": d.id, "kind": d.kind, "name": d.name, "name_am": d.name_am, "capacity": d.capacity,
            "active": d.active}


class DepartmentCreate(BaseModel):
    kind: str
    name: Name = Field(max_length=120)
    name_am: OptionalText = Field(default=None, max_length=120)
    capacity: Optional[int] = Field(default=None, ge=0, le=5000)


class DepartmentUpdate(BaseModel):
    name: Optional[Name] = Field(default=None, max_length=120)
    name_am: OptionalText = Field(default=None, max_length=120)
    capacity: Optional[int] = Field(default=None, ge=0, le=5000)
    active: Optional[bool] = None


@router.get("/departments")
def list_departments(
    kind: Optional[str] = None,
    include_inactive: bool = False,
    staff: Staff = Depends(current_staff),
) -> List[Dict[str, Any]]:
    if kind is not None and kind not in DepartmentKind.ALL:
        raise HTTPException(status_code=400, detail=f"kind must be one of {list(DepartmentKind.ALL)}.")
    with session_scope() as session:
        query = select(Department).where(Department.hospital_id == staff.hospital_id)
        if kind:
            query = query.where(Department.kind == kind)
        if not include_inactive:
            query = query.where(Department.active.is_(True))
        return [department_payload(d) for d in session.scalars(query.order_by(Department.kind, Department.name))]


@router.post("/departments", status_code=status.HTTP_201_CREATED)
def create_department(body: DepartmentCreate, staff: Staff = Depends(admin_only)) -> Dict[str, Any]:
    if body.kind not in DepartmentKind.ALL:
        raise HTTPException(status_code=400, detail=f"kind must be one of {list(DepartmentKind.ALL)}.")
    if body.capacity is not None and body.kind != DepartmentKind.WARD:
        raise HTTPException(status_code=400, detail="Only a ward has a bed capacity.")
    try:
        with session_scope() as session:
            department = Department(hospital_id=staff.hospital_id, kind=body.kind, name=body.name,
                                    name_am=body.name_am, capacity=body.capacity)
            session.add(department)
            session.flush()
            audit(session, staff.hospital_id, staff.id, "department_created", "department", department.id)
            return department_payload(department)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A department of this kind with this name exists.") from exc


@router.patch("/departments/{department_id}")
def update_department(department_id: str, body: DepartmentUpdate, staff: Staff = Depends(admin_only)) -> Dict[str, Any]:
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if not (k in ("name", "active") and v is None)}
    try:
        with session_scope() as session:
            department = session.scalar(select(Department).where(
                Department.id == department_id, Department.hospital_id == staff.hospital_id))
            if department is None:
                raise HTTPException(status_code=404, detail="Department not found.")
            if changes.get("capacity") is not None and department.kind != DepartmentKind.WARD:
                raise HTTPException(status_code=400, detail="Only a ward has a bed capacity.")
            for field, value in changes.items():
                setattr(department, field, value)
            audit(session, staff.hospital_id, staff.id, "department_updated", "department", department.id,
                  {"fields": sorted(changes)})
            return department_payload(department)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A department of this kind with this name exists.") from exc


# --- staff accounts ---------------------------------------------------------------

class StaffCreate(BaseModel):
    email: EmailStr
    full_name: Name = Field(max_length=120)
    full_name_am: OptionalText = Field(default=None, max_length=120)
    role: str
    department_id: OptionalText = Field(default=None, max_length=32)
    phone: OptionalPhone = None


class StaffUpdate(BaseModel):
    full_name: Optional[Name] = Field(default=None, max_length=120)
    full_name_am: OptionalText = Field(default=None, max_length=120)
    role: Optional[str] = None
    department_id: OptionalText = Field(default=None, max_length=32)
    phone: OptionalPhone = None
    active: Optional[bool] = None


#: Emails are unique across all hospitals; the message does not say whether
#: the clash is in this hospital or another one.
EMAIL_TAKEN = "This email cannot be used for a new account."



def _check_role(role: Optional[str]) -> None:
    if role is not None and role not in Role.ALL:
        raise HTTPException(status_code=400, detail=f"role must be one of {list(Role.ALL)}.")


def _check_department(session, hospital_id: str, department_id: Optional[str]) -> None:
    if department_id and session.scalar(select(Department.id).where(
            Department.id == department_id, Department.hospital_id == hospital_id)) is None:
        raise HTTPException(status_code=400, detail="Unknown department.")


def _other_active_admins(session, hospital_id: str, user_id: str) -> int:
    # The rows are locked, so two admins demoting each other at the same
    # moment cannot both pass this check and leave the hospital with none.
    return len(session.scalars(select(StaffUser.id).where(
        StaffUser.hospital_id == hospital_id, StaffUser.role == Role.ADMIN,
        StaffUser.active.is_(True), StaffUser.id != user_id).with_for_update()).all())


@router.get("/staff")
def list_staff(
    role: Optional[str] = None,
    q: Optional[str] = Query(default=None, max_length=120),
    include_inactive: bool = False,
    staff: Staff = Depends(admin_only),
) -> List[Dict[str, Any]]:
    _check_role(role)
    with session_scope() as session:
        query = select(StaffUser).where(StaffUser.hospital_id == staff.hospital_id)
        if role:
            query = query.where(StaffUser.role == role)
        if not include_inactive:
            query = query.where(StaffUser.active.is_(True))
        if q and q.strip():
            like = f"%{q.strip().lower()}%"
            query = query.where(or_(func.lower(StaffUser.full_name).like(like), StaffUser.email.like(like)))
        return [staff_payload(u) for u in session.scalars(query.order_by(StaffUser.full_name))]


@router.post("/staff", status_code=status.HTTP_201_CREATED)
def create_staff(body: StaffCreate, staff: Staff = Depends(admin_only)) -> Dict[str, Any]:
    """Create an account with a one-time password to hand over in person."""
    _check_role(body.role)
    password = temporary_password()
    try:
        with session_scope() as session:
            _check_department(session, staff.hospital_id, body.department_id)
            user = StaffUser(
                hospital_id=staff.hospital_id, email=body.email.lower(), full_name=body.full_name.strip(),
                full_name_am=body.full_name_am, role=body.role, department_id=body.department_id,
                phone=body.phone, password_hash=hash_password(password), must_change_password=True,
            )
            session.add(user)
            session.flush()
            audit(session, staff.hospital_id, staff.id, "staff_created", "staff", user.id, {"role": body.role})
            return {**staff_payload(user), "temporary_password": password}
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail=EMAIL_TAKEN) from exc


@router.patch("/staff/{user_id}")
def update_staff(user_id: str, body: StaffUpdate, staff: Staff = Depends(admin_only)) -> Dict[str, Any]:
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items()
               if not (k in ("full_name", "role", "active") and v is None)}
    _check_role(changes.get("role"))
    try:
        with session_scope() as session:
            user = session.scalar(select(StaffUser).where(
                StaffUser.id == user_id, StaffUser.hospital_id == staff.hospital_id).with_for_update())
            if user is None:
                raise HTTPException(status_code=404, detail="Staff member not found.")
            if "department_id" in changes:
                _check_department(session, staff.hospital_id, changes["department_id"])
            losing_admin = user.role == Role.ADMIN and (
                changes.get("role", Role.ADMIN) != Role.ADMIN or changes.get("active") is False)
            if losing_admin and _other_active_admins(session, staff.hospital_id, user.id) == 0:
                raise HTTPException(status_code=400, detail="The hospital must keep at least one active admin.")
            for field, value in changes.items():
                setattr(user, field, value)
            if changes.get("active") is False:
                auth.revoke_all_sessions(session, user.id)
            audit(session, staff.hospital_id, staff.id, "staff_updated", "staff", user.id,
                  {"fields": sorted(changes)})
            return staff_payload(user)
    except IntegrityError as exc:
        # A department deleted between the check and the commit.
        raise HTTPException(status_code=409, detail="The change conflicts with other data; reload and retry.") from exc


@router.post("/staff/{user_id}/reset-password")
def reset_staff_password(user_id: str, staff: Staff = Depends(admin_only)) -> Dict[str, Any]:
    """A new one-time password; the account's sessions end."""
    password = temporary_password()
    with session_scope() as session:
        user = session.scalar(select(StaffUser).where(
            StaffUser.id == user_id, StaffUser.hospital_id == staff.hospital_id))
        if user is None:
            raise HTTPException(status_code=404, detail="Staff member not found.")
        user.password_hash = hash_password(password)
        user.must_change_password = True
        user.failed_logins = 0
        user.last_failed_at = None
        user.locked_until = None
        auth.revoke_all_sessions(session, user.id)
        audit(session, staff.hospital_id, staff.id, "staff_password_reset", "staff", user.id)
        return {"id": user.id, "temporary_password": password}
