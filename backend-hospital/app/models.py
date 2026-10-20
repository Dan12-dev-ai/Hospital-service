"""Tables of the hospital service.

Every row that belongs to a hospital carries ``hospital_id``, and every API
query is scoped to the signed-in staff member's hospital.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text,
)
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


class PatientStatus:
    """Where a patient is in their care. The values match the portal's tabs."""

    #: Seen as an outpatient (the default once registered).
    OPD = "opd"
    EMERGENCY = "emergency"
    #: In a ward bed.
    ADMITTED = "admitted"
    #: Still in a bed, cleared to go home.
    DISCHARGE = "discharge"
    #: Has left the ward.
    DISCHARGED = "discharged"
    ALL = (OPD, EMERGENCY, ADMITTED, DISCHARGE, DISCHARGED)
    #: Statuses in which the patient occupies a bed.
    IN_BED = (ADMITTED, DISCHARGE)


class Sex:
    FEMALE = "female"
    MALE = "male"
    ALL = (FEMALE, MALE)


class Payer:
    CASH = "cash"
    #: Community-Based Health Insurance.
    CBHI = "cbhi"
    PRIVATE = "private"
    #: Employer or government credit agreement.
    CREDIT = "credit"
    ALL = (CASH, CBHI, PRIVATE, CREDIT)


class AlertKind:
    ALLERGY = "allergy"
    RISK = "risk"
    ALL = (ALLERGY, RISK)


class DutyStatus:
    """A doctor's duty status. The values match the portal's filters."""

    ON_DUTY = "on-duty"
    IN_CONSULTATION = "in-consultation"
    ON_CALL = "on-call"
    OFF_DUTY = "off-duty"
    ALL = (ON_DUTY, IN_CONSULTATION, ON_CALL, OFF_DUTY)


class DoctorRank:
    CHIEF = "chief"
    SENIOR_CONSULTANT = "senior-consultant"
    ATTENDING = "attending"
    RESIDENT = "resident"
    ALL = (CHIEF, SENIOR_CONSULTANT, ATTENDING, RESIDENT)


class HospitalStatus:
    """Where a hospital is in Endod's onboarding."""

    #: Signed up through the portal; not yet shown to patients.
    PENDING = "pending"
    #: Checked by Endod: listed in the patient app and bookable.
    APPROVED = "approved"
    #: Taken off the patient app (by Endod).
    SUSPENDED = "suspended"
    ALL = (PENDING, APPROVED, SUSPENDED)


class HospitalKind:
    PUBLIC = "public"
    PRIVATE = "private"
    ALL = (PUBLIC, PRIVATE)


class Service:
    """What a hospital offers, in the patient app's terms (shared taxonomy)."""

    GENERAL = "general_medicine"
    EMERGENCY = "emergency"
    MATERNAL = "maternal_health"
    PEDIATRICS = "pediatrics"
    CARDIOLOGY = "cardiology"
    RESPIRATORY = "respiratory"
    ALL = (GENERAL, EMERGENCY, MATERNAL, PEDIATRICS, CARDIOLOGY, RESPIRATORY)


class VisitMode:
    IN_PERSON = "in_person"
    VIDEO = "video"
    ALL = (IN_PERSON, VIDEO)


class BookingStatus:
    """An appointment booked by a patient through Endod."""

    #: A video visit waiting for a doctor to approve it.
    AWAITING_DOCTOR = "awaiting_doctor"
    #: In-person visits are confirmed on arrival; video ones once approved.
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    #: Cancelled by the patient (through Endod) or by the hospital.
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    ALL = (AWAITING_DOCTOR, CONFIRMED, REJECTED, CANCELLED, COMPLETED)
    OPEN = (AWAITING_DOCTOR, CONFIRMED)


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
    #: The last hospital number issued; the next patient gets this plus one.
    mrn_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    # --- What patients see in the Endod app (listed once approved) ---
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=HospitalStatus.APPROVED,
                                        server_default=text("'approved'"))
    kind: Mapped[str] = mapped_column(String(8), nullable=False, default=HospitalKind.PUBLIC,
                                      server_default=text("'public'"))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    address: Mapped[Optional[str]] = mapped_column(String(200))
    #: +251XXXXXXXXX, or a short landline / hotline.
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    ambulance_phone: Mapped[Optional[str]] = mapped_column(String(20))
    #: Has a 24-hour emergency department.
    emergency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    #: Comma-separated Service values.
    services: Mapped[Optional[str]] = mapped_column(String(200))
    open_hours: Mapped[Optional[str]] = mapped_column(String(80))
    video_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    #: Visit prices in santim (1/100 birr); set by the hospital.
    price_in_person: Mapped[Optional[int]] = mapped_column(Integer)
    price_video: Mapped[Optional[int]] = mapped_column(Integer)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: Raised on every announcement, so the platform can ignore an older one
    #: that arrives late.
    listing_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))


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


class DoctorProfile(Base):
    """What the directory shows about a doctor beyond their staff account."""

    __tablename__ = "doctor_profiles"
    __table_args__ = (UniqueConstraint("hospital_id", "license_number", name="uq_doctor_license"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("staff_users.id", ondelete="CASCADE"), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False, index=True)
    #: Ethiopian Medical Council licence number.
    license_number: Mapped[Optional[str]] = mapped_column(String(40))
    credentials: Mapped[Optional[str]] = mapped_column(String(80))
    specialty: Mapped[Optional[str]] = mapped_column(String(120))
    rank: Mapped[Optional[str]] = mapped_column(String(24))
    extension: Mapped[Optional[str]] = mapped_column(String(16))
    #: How many patients the doctor can see in a day; the load bar is measured against it.
    daily_capacity: Mapped[Optional[int]] = mapped_column(Integer)
    duty_status: Mapped[str] = mapped_column(String(20), nullable=False, default=DutyStatus.OFF_DUTY)
    #: Where, while on duty: "OPD Rm 204", "OR-3".
    duty_location: Mapped[Optional[str]] = mapped_column(String(60))
    duty_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("hospital_id", "mrn", name="uq_patient_mrn"),
        UniqueConstraint("hospital_id", "dedan_id", name="uq_patient_dedan_id"),
        Index("ix_patients_hospital_status", "hospital_id", "status"),
        Index("ix_patients_hospital_phone", "hospital_id", "phone"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    #: The hospital number, e.g. "SPH-000124". Issued once, never reused.
    mrn: Mapped[str] = mapped_column(String(24), nullable=False)
    #: The patient's Endod (DEDAN) digital health ID, e.g. "DE-482731", when linked.
    dedan_id: Mapped[Optional[str]] = mapped_column(String(40))
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    full_name_am: Mapped[Optional[str]] = mapped_column(String(120))
    sex: Mapped[str] = mapped_column(String(8), nullable=False)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date)
    #: True when only an age was given and the date of birth is worked out from it.
    dob_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: +251XXXXXXXXX.
    phone: Mapped[Optional[str]] = mapped_column(String(16))
    address: Mapped[Optional[str]] = mapped_column(String(200))
    emergency_contact_name: Mapped[Optional[str]] = mapped_column(String(120))
    emergency_contact_phone: Mapped[Optional[str]] = mapped_column(String(16))
    payer: Mapped[str] = mapped_column(String(12), nullable=False, default=Payer.CASH)
    #: CBHI membership or insurance policy number.
    payer_number: Mapped[Optional[str]] = mapped_column(String(40))

    status: Mapped[str] = mapped_column(String(12), nullable=False, default=PatientStatus.OPD)
    department_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    ward_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    bed: Mapped[Optional[str]] = mapped_column(String(16))
    attending_doctor_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL"), index=True)
    #: The working diagnosis shown in the directory.
    diagnosis: Mapped[Optional[str]] = mapped_column(String(200))
    status_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow,
                                                 onupdate=utcnow)


class PatientAlert(Base):
    """An allergy or risk shown on the patient's row and chart."""

    __tablename__ = "patient_alerts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Booking(Base):
    """An appointment a patient booked at this hospital through the Endod app.

    Created from the platform's ``appointment.requested`` event; every change
    here is sent back as an event. The patient has already paid Endod (the
    price in ``price``); Endod pays the hospital.
    """

    __tablename__ = "bookings"
    __table_args__ = (Index("ix_bookings_hospital_time", "hospital_id", "scheduled_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    #: The appointment's id in the Endod platform.
    external_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    patient_dedan_id: Mapped[str] = mapped_column(String(16), nullable=False)
    patient_name: Mapped[str] = mapped_column(String(160), nullable=False)
    patient_phone: Mapped[Optional[str]] = mapped_column(String(20))
    visit_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    service: Mapped[Optional[str]] = mapped_column(String(40))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    #: Santim the patient paid for the visit (Endod's fee is not included).
    price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The doctor who approved (video) or was assigned.
    doctor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    #: Jitsi room of a video visit, set when a doctor approves it.
    meeting_room: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    reason: Mapped[Optional[str]] = mapped_column(String(300))
    decided_by: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow,
                                                 onupdate=utcnow)


class OutboxEvent(Base):
    """An event waiting to be sent to the Endod platform.

    Written in the same transaction as the change it describes, so a change is
    never saved without its event or announced without being saved.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_unpublished", "published_at", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ProcessedEvent(Base):
    """An event from the platform already handled (so a redelivery is skipped)."""

    __tablename__ = "processed_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
