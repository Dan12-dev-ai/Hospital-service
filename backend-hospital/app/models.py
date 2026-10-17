"""Tables of the hospital service.

Every row that belongs to a hospital carries ``hospital_id``, and every API
query is scoped to the signed-in staff member's hospital.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, new_id, utcnow


class Role:
    ADMIN = "admin"
    DOCTOR = "doctor"
    NURSE = "nurse"
    RECEPTION = "reception"
    PHARMACIST = "pharmacist"
    BILLING = "billing"
    RECORDS = "records"
    ALL = (ADMIN, DOCTOR, NURSE, RECEPTION, PHARMACIST, BILLING, RECORDS)


class DepartmentKind:
    #: A clinical department (Internal Medicine, Pediatrics, ...).
    DEPARTMENT = "department"
    #: An in-patient ward with beds.
    WARD = "ward"
    #: An outpatient clinic or desk where patients are registered and billed.
    CLINIC = "clinic"
    #: A pharmacy dispensary.
    DISPENSARY = "dispensary"
    ALL = (DEPARTMENT, WARD, CLINIC, DISPENSARY)


class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    #: Short code used in hospital numbers (MRN prefix), e.g. "SPH".
    code: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    name_am: Mapped[Optional[str]] = mapped_column(String(160))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Africa/Addis_Ababa")
    #: The facility's id in the patient platform's care directory, when listed.
    directory_facility_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("hospital_id", "kind", "name", name="uq_department_name"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_am: Mapped[Optional[str]] = mapped_column(String(120))
    #: Beds, for a ward.
    capacity: Mapped[Optional[int]] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class StaffUser(Base):
    __tablename__ = "staff_users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    full_name_am: Mapped[Optional[str]] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    department_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Set when an admin issues a temporary password; the next sign-in must change it.
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    department: Mapped[Optional[Department]] = relationship()


class StaffSession(Base):
    """A signed-in session. The client holds a random token; only its hash is stored."""

    __tablename__ = "staff_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("staff_users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[Optional[str]] = mapped_column(String(200))


class AuditEvent(Base):
    """Who did what, for accountability on patient data."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_hospital_at", "hospital_id", "at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    actor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(32))
    target_id: Mapped[Optional[str]] = mapped_column(String(64))
    detail: Mapped[Optional[str]] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
