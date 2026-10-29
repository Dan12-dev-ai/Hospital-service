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
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db import Base, new_id, utcnow
from app.validation import checked_dedan_id

# Every column holding a confirmed Endod ID accepts only its stored form
# (DE + 6 digits): see the ``_check_dedan`` validators below.


def SealedText(length: int):  # noqa: N802 -- a column type factory
    """A text column encrypted at rest (app/sealing.py lists them all).

    The API still limits the plain text to ``length`` characters; the stored
    ciphertext is longer, so on PostgreSQL the column is TEXT. SQLite never
    enforces a VARCHAR's length, and keeps the original type (no table rebuild).
    """
    return String(length).with_variant(Text(), "postgresql")


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
    """Ownership (the column and API field are called ``kind`` for history)."""

    PUBLIC = "public"
    PRIVATE = "private"
    ALL = (PUBLIC, PRIVATE)


class FacilityType:
    HOSPITAL = "hospital"
    CLINIC = "clinic"
    ALL = (HOSPITAL, CLINIC)


class ApplicationStatus:
    """Where a pending hospital is in its onboarding application."""

    #: Filling in the wizard.
    DRAFT = "draft"
    #: Sent to Endod; waiting for the demo and review.
    SUBMITTED = "submitted"
    #: Sent back by Endod with a reason; the hospital fixes it and resubmits.
    REJECTED = "rejected"
    APPROVED = "approved"
    ALL = (DRAFT, SUBMITTED, REJECTED, APPROVED)
    #: The hospital may change its application in these.
    EDITABLE = (DRAFT, REJECTED)


class DocumentKind:
    """The documents every applicant must upload."""

    MOH_LICENSE = "moh_license"
    TRADE_LICENSE = "trade_license"
    TIN_CERTIFICATE = "tin_certificate"
    OWNER_ID = "owner_id"
    ALL = (MOH_LICENSE, TRADE_LICENSE, TIN_CERTIFICATE, OWNER_ID)
    LABELS = {
        MOH_LICENSE: "Ministry of Health facility license",
        TRADE_LICENSE: "Business / trade license",
        TIN_CERTIFICATE: "TIN certificate",
        OWNER_ID: "Owner or manager's ID",
    }


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
    #: A hospital or a clinic.
    facility_type: Mapped[str] = mapped_column(String(8), nullable=False, default=FacilityType.HOSPITAL,
                                               server_default=text("'hospital'"))
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
    #: Queue: how many people ahead triggers the "get ready" SMS (0 = off).
    queue_notify_ahead: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default=text("3"))


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

    # --- Two-step verification (app/twofactor.py; migration 0010) ---
    #: The authenticator's TOTP secret (encrypted at rest). One being set up
    #: waits on its own sign-in session (StaffSession.totp_pending_secret).
    totp_secret: Mapped[Optional[str]] = mapped_column(Text)
    #: The newest TOTP step used: that code, and every older one, never works again.
    totp_last_step: Mapped[Optional[int]] = mapped_column(Integer)
    totp_enrolled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: Wrong codes for this account from anywhere, and the pause they caused (no session ends).
    code_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    code_last_failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    code_backoff_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    department: Mapped[Optional[Department]] = relationship()


class SessionStage:
    #: Signed in (password, and a code where two-step verification applies).
    FULL = "full"
    #: The password was right; a code from the authenticator (or a recovery code) is next.
    TOTP = "totp"
    #: The password was right; an authenticator must be set up first.
    ENROLL = "enroll"
    ALL = (FULL, TOTP, ENROLL)


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
    #: SessionStage; sessions from before migration 0010 are full ones.
    stage: Mapped[str] = mapped_column(String(8), nullable=False, default=SessionStage.FULL,
                                       server_default=text("'full'"))
    #: When the staff member last gave a fresh authenticator code in this session (re-authentication).
    reauth_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: An ``enroll`` session's own new TOTP secret, until its first code
    #: confirms it (encrypted at rest): each set-up session has a fresh one.
    totp_pending_secret: Mapped[Optional[str]] = mapped_column(Text)


class StaffRecoveryCode(Base):
    """A one-time recovery code (only its keyed hash), ten per enrolment."""

    __tablename__ = "staff_recovery_codes"
    __table_args__ = (Index("ix_staff_recovery_codes_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False,
                                             index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("staff_users.id", ondelete="CASCADE"), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


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
    #: The patient's Endod (DEDAN) digital health ID, e.g. "DE482731". Set only
    #: once Endod confirmed the account (patient.linked, or checking in an
    #: Endod booking); see app.linking.
    dedan_id: Mapped[Optional[str]] = mapped_column(String(40))
    #: An Endod ID the patient gave (or staff typed) but nobody confirmed:
    #: shown as "Endod ID given, not yet linked", never sent to Endod.
    claimed_dedan_id: Mapped[Optional[str]] = mapped_column(String(40))
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
    #: The working diagnosis shown in the directory (encrypted at rest).
    diagnosis: Mapped[Optional[str]] = mapped_column(SealedText(200))
    status_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow,
                                                 onupdate=utcnow)

    @validates("dedan_id")
    def _check_dedan(self, _key: str, value: Optional[str]) -> Optional[str]:
        return checked_dedan_id(value)


class PatientAlert(Base):
    """An allergy or risk shown on the patient's row and chart."""

    __tablename__ = "patient_alerts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    #: The patient's hospital (so the database can keep the alert, its patient
    #: and its author in one hospital: app/rls.py).
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False,
                                             index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    #: Encrypted at rest (an allergy or risk is health data).
    label: Mapped[str] = mapped_column(SealedText(120), nullable=False)
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
    #: The patient's note when booking (often symptoms): encrypted at rest.
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


# --- Patient history: linking, records, visits, queues, shared records, imports ---
# The contract with the patient platform is docs/history-events.md.

class LinkStatus:
    PENDING = "pending"
    LINKED = "linked"
    REFUSED = "refused"
    #: Replaced by a newer request, or the patient was linked another way.
    SUPERSEDED = "superseded"
    ALL = (PENDING, LINKED, REFUSED, SUPERSEDED)


class PatientLinkRequest(Base):
    """A request to Endod to link a hospital patient to an Endod account.

    The patient's ``dedan_id`` is set (and records published) only once the
    platform answers ``patient.linked``.
    """

    __tablename__ = "patient_link_requests"
    __table_args__ = (Index("ix_link_requests_patient", "patient_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    dedan_id: Mapped[str] = mapped_column(String(16), nullable=False)
    #: "card" (the QR's signature) or "phone".
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=LinkStatus.PENDING)
    #: The platform's reason on refusal ("not_found", "not_verified"), or ours.
    reason: Mapped[Optional[str]] = mapped_column(String(40))
    #: The account holder's name, as Endod confirmed it.
    linked_name: Mapped[Optional[str]] = mapped_column(String(160))
    requested_by: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    @validates("dedan_id")
    def _check_dedan(self, _key: str, value: Optional[str]) -> Optional[str]:
        return checked_dedan_id(value)


class RecordCategory:
    DIAGNOSIS = "diagnosis"
    PRESCRIPTION = "prescription"
    LAB_RESULT = "lab_result"
    IMAGING = "imaging"
    VISIT_NOTE = "visit_note"
    DOCUMENT = "document"
    ALL = (DIAGNOSIS, PRESCRIPTION, LAB_RESULT, IMAGING, VISIT_NOTE, DOCUMENT)


class Visit(Base):
    """A visit groups clinical records and may carry a follow-up date."""

    __tablename__ = "visits"
    __table_args__ = (Index("ix_visits_patient", "patient_id", "started_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    doctor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    booking_id: Mapped[Optional[str]] = mapped_column(ForeignKey("bookings.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    follow_up_on: Mapped[Optional[date]] = mapped_column(Date)
    #: Encrypted at rest.
    follow_up_note: Mapped[Optional[str]] = mapped_column(SealedText(500))
    #: The Endod ID the current follow-up was sent to (so its cancellation reaches the same account).
    follow_up_sent_to: Mapped[Optional[str]] = mapped_column(String(16))
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    @validates("follow_up_sent_to")
    def _check_dedan(self, _key: str, value: Optional[str]) -> Optional[str]:
        return checked_dedan_id(value)


class ClinicalRecord(Base):
    __tablename__ = "clinical_records"
    __table_args__ = (
        Index("ix_records_patient", "patient_id", "occurred_at"),
        UniqueConstraint("hospital_id", "import_key", name="uq_record_import_key"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    visit_id: Mapped[Optional[str]] = mapped_column(ForeignKey("visits.id", ondelete="SET NULL"))
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Encrypted at rest, like ``details``: a title often names the diagnosis.
    title: Mapped[str] = mapped_column(SealedText(200), nullable=False)
    #: A JSON object, by category (docs/history-events.md, section 2). Encrypted at rest.
    details: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The staff member who wrote it (none for an import).
    recorded_by: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    #: The name the patient sees: the author, or the clinician named in an import.
    recorded_by_name: Mapped[Optional[str]] = mapped_column(String(160))
    #: "portal" or "import".
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="portal")
    #: Raised on every correction; the platform keeps the highest.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retracted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retracted_reason: Mapped[Optional[str]] = mapped_column(String(300))
    retracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: The Endod ID it was last published to (None: never published).
    published_dedan_id: Mapped[Optional[str]] = mapped_column(String(16))
    #: The Endod ID it was last taken off (record.retracted sent there), never
    #: cleared: a dispense the platform made just before the retraction still
    #: counts (docs/pharmacy.md, section 4).
    previous_dedan_id: Mapped[Optional[str]] = mapped_column(String(16))
    #: The version last sent to Endod (None: never). A correction made while the
    #: patient was unlinked (version > published_version) is sent on re-linking.
    published_version: Mapped[Optional[int]] = mapped_column(Integer)
    #: An imported record: sha256 of its source item (the FHIR resource or CSV
    #: row), unique per hospital, so the same item is never imported twice.
    import_key: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow,
                                                 onupdate=utcnow)

    @validates("published_dedan_id", "previous_dedan_id")
    def _check_dedan(self, _key: str, value: Optional[str]) -> Optional[str]:
        return checked_dedan_id(value)


class RecordFile(Base):
    """A PDF or image kept on disk under HOSPITAL_FILES_DIR.

    Uploaded first (no ``record_id``), then attached to a record. Its path on
    disk is built from the hospital and file ids only, never from a name.
    """

    __tablename__ = "record_files"
    __table_args__ = (Index("ix_record_files_record", "record_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    record_id: Mapped[Optional[str]] = mapped_column(ForeignKey("clinical_records.id", ondelete="CASCADE"))
    #: Encrypted at rest ("hiv-test.pdf" says as much as the file); so is the file itself.
    filename: Mapped[str] = mapped_column(SealedText(160), nullable=False)
    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The data key version the file on disk is encrypted with (None: plain
    #: text, stored before encryption). Kept in step with the file by
    #: app/rekey.py, so migration 0008's downgrade can see, without the files,
    #: whether any file still needs the keys.
    key_version: Mapped[Optional[int]] = mapped_column(Integer)
    uploaded_by: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class QueueStatus:
    WAITING = "waiting"
    CALLED = "called"
    DONE = "done"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    ALL = (WAITING, CALLED, DONE, SKIPPED, CANCELLED)
    OPEN = (WAITING, CALLED)


class QueueDay(Base):
    """One doctor's queue on one day: its ticket counter, and the row every
    change to that queue locks first (so changes happen one at a time)."""

    __tablename__ = "queue_days"
    __table_args__ = (UniqueConstraint("hospital_id", "doctor_id", "day", name="uq_queue_day"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("staff_users.id", ondelete="CASCADE"), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    last_ticket: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Bumped by every change: the write that takes the row lock.
    changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class QueueEntry(Base):
    __tablename__ = "queue_entries"
    __table_args__ = (
        UniqueConstraint("queue_id", "ticket", name="uq_queue_ticket"),
        Index("ix_queue_entries_queue_status", "queue_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    queue_id: Mapped[str] = mapped_column(ForeignKey("queue_days.id", ondelete="CASCADE"), nullable=False)
    ticket: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=QueueStatus.WAITING)
    patient_id: Mapped[Optional[str]] = mapped_column(ForeignKey("patients.id", ondelete="SET NULL"))
    #: One entry per Endod booking.
    booking_id: Mapped[Optional[str]] = mapped_column(ForeignKey("bookings.id", ondelete="SET NULL"), unique=True)
    dedan_id: Mapped[Optional[str]] = mapped_column(String(16))
    patient_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    #: People ahead when last announced (-1: never announced).
    last_ahead: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    near_notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    turn_notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Raised with every queue.updated sent for this entry.
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checked_in_by: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    checked_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    called_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    @validates("dedan_id")
    def _check_dedan(self, _key: str, value: Optional[str]) -> Optional[str]:
        return checked_dedan_id(value)


class RecordShare(Base):
    """Records a patient shared with this hospital through Endod (a read-only copy).

    The copy is deleted when unshared or expired; the row stays a little
    while as a tombstone (``revoked_at``) so a late ``records.shared`` is not stored.
    """

    __tablename__ = "record_shares"
    __table_args__ = (Index("ix_record_shares_hospital_dedan", "hospital_id", "dedan_id"),)

    #: The platform's share id.
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    dedan_id: Mapped[Optional[str]] = mapped_column(String(16))
    patient_name: Mapped[Optional[str]] = mapped_column(String(160))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    @validates("dedan_id")
    def _check_dedan(self, _key: str, value: Optional[str]) -> Optional[str]:
        return checked_dedan_id(value)


class SharedRecord(Base):
    __tablename__ = "shared_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    share_id: Mapped[str] = mapped_column(ForeignKey("record_shares.id", ondelete="CASCADE"), nullable=False,
                                          index=True)
    record_id: Mapped[str] = mapped_column(String(32), nullable=False)
    origin: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The copy's title, details and file list are encrypted at rest.
    title: Mapped[str] = mapped_column(SealedText(200), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[Optional[str]] = mapped_column(String(160))
    #: A JSON list of {file_id, filename, content_type, size, sha256}.
    files: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class ImportBatch(Base):
    """An uploaded FHIR bundle or CSV, previewed and waiting for confirmation."""

    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    #: "fhir" or "csv".
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    filename: Mapped[Optional[str]] = mapped_column(String(160))
    #: JSON: {"items": [...], "skipped": [...]} (the records to be, with their
    #: details): encrypted at rest. The uploaded file itself is never stored.
    plan: Mapped[str] = mapped_column(Text, nullable=False)
    #: "previewed" or "imported".
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="previewed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    imported_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# --- Hospital onboarding: the application, its documents and the demo -------------------

class OnboardingApplication(Base):
    """A pending hospital's application to join Endod (one per hospital)."""

    __tablename__ = "onboarding_applications"

    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=ApplicationStatus.DRAFT)
    #: The contact person's role or title (the person is the first admin account).
    contact_title: Mapped[Optional[str]] = mapped_column(String(80))
    #: The Ministry of Health facility license number.
    license_number: Mapped[Optional[str]] = mapped_column(String(60))
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: Endod's reason, shown to the hospital until it resubmits.
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow,
                                                 onupdate=utcnow)


class OnboardingDocument(Base):
    """One required document, kept on disk under HOSPITAL_FILES_DIR (see app.files).

    Replacing a document keeps the row and points it at the new file.
    """

    __tablename__ = "onboarding_documents"
    __table_args__ = (UniqueConstraint("hospital_id", "kind", name="uq_onboarding_document_kind"),)

    #: Also the file's id on disk.
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(160), nullable=False)
    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The data key version the file on disk is encrypted with (None: plain
    #: text, stored before encryption). Kept in step with the file by
    #: app/rekey.py, so migration 0008's downgrade can see, without the files,
    #: whether any file still needs the keys.
    key_version: Mapped[Optional[int]] = mapped_column(Integer)
    uploaded_by: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class DemoBooking(Base):
    """The 30-minute demo a pending hospital booked with Endod.

    One per hospital, one hospital per slot and one per contact mobile: all
    unique, so two hospitals racing for the same time cannot both get it. A
    booking is released (deleted) when its application is not submitted
    within a day of booking, or is sent back or suspended (app.onboarding).
    """

    __tablename__ = "demo_bookings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False,
                                             unique=True)
    #: The start of the slot, in UTC.
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, unique=True)
    #: The contact person's mobile (+251...): one active demo per number,
    #: across hospitals, so one person cannot hold many slots.
    phone: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow,
                                                 onupdate=utcnow)


# --- Prescriptions dispensed at pharmacies (docs/pharmacy.md, section 4) ---

class PrescriptionDispense(Base):
    """Medicine given at a pharmacy from one of this hospital's prescription
    records, as Endod reported it (``prescription.dispensed``)."""

    __tablename__ = "prescription_dispenses"
    __table_args__ = (Index("ix_prescription_dispenses_record", "record_id", "dispensed_at"),)

    #: The platform's dispense_id: a dispense is stored once, however often it arrives.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    record_id: Mapped[str] = mapped_column(ForeignKey("clinical_records.id", ondelete="CASCADE"), nullable=False)
    dedan_id: Mapped[str] = mapped_column(String(16), nullable=False)
    #: As the pharmacist typed it (not verified).
    pharmacy_name: Mapped[str] = mapped_column(String(120), nullable=False)
    dispensed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The prescription's status after this dispense: "open" or "completed".
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    #: A JSON list of {item_index, amount, complete, given_total, status}.
    items: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    @validates("dedan_id")
    def _check_dedan(self, _key: str, value: Optional[str]) -> Optional[str]:
        return checked_dedan_id(value)


# --- Encryption at rest (app/crypto.py, app/sealing.py) ---

class HospitalKey(Base):
    """A hospital's data key, wrapped (AES-256-GCM) under the master key.

    One version is active (new data is encrypted with it); older versions
    stay to read what was encrypted before a rotation, until re-encrypted.
    """

    __tablename__ = "hospital_keys"
    __table_args__ = (UniqueConstraint("hospital_id", "version", name="uq_hospital_keys_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False,
                                             index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: base64 of nonce, wrapped key and tag; the associated data names the hospital and version.
    wrapped_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EncryptionState(Base):
    """One row (id 1): whether plaintext is refused (``enforce-encryption``).
    Belongs to no hospital; the app reads it, only Endod's CLI changes it."""

    __tablename__ = "encryption_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Since when values and files not encrypted are refused (None: not enforced yet).
    enforced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: Which master key this database belongs to: an HMAC of a fixed label
    #: under it (app/crypto.py, ``kek_check``), its fingerprint, and when it
    #: was recorded (first start, or first data key). A different key is refused.
    kek_check: Mapped[Optional[str]] = mapped_column(String(64))
    kek_fingerprint: Mapped[Optional[str]] = mapped_column(String(16))
    kek_recorded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# --- Integration API for hospitals' own systems (app/integrations, docs/integrations.md) ---

class IntegrationMode:
    #: Writes real records.
    LIVE = "live"
    #: Checks and maps everything, stores nothing.
    TEST = "test"
    ALL = (LIVE, TEST)


class IntegrationAuth:
    #: A random secret (only its argon2 hash is kept).
    SECRET = "client_secret"
    #: A signed client assertion, checked against the client's public keys (SMART Backend Services).
    PRIVATE_KEY_JWT = "private_key_jwt"
    ALL = (SECRET, PRIVATE_KEY_JWT)


class DeliveryStatus:
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    ALL = (PENDING, DELIVERED, FAILED)


class IntegrationClient(Base):
    """A hospital system connected to the integration API (OAuth 2.0 client
    credentials). Never deleted: disconnecting sets ``revoked_at``."""

    __tablename__ = "integration_clients"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False,
                                             index=True)
    #: Public (the OAuth client_id).
    client_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    #: Granted scopes, space-separated (app/integrations/scopes.py).
    scopes: Mapped[str] = mapped_column(String(400), nullable=False)
    mode: Mapped[str] = mapped_column(String(4), nullable=False, default=IntegrationMode.LIVE)
    auth_method: Mapped[str] = mapped_column(String(20), nullable=False, default=IntegrationAuth.SECRET)
    #: argon2id hash of the client secret (client_secret auth only).
    secret_hash: Mapped[Optional[str]] = mapped_column(String(255))
    #: The client's public keys (a JWKS, JSON; private_key_jwt auth only). Public, not encrypted.
    jwks: Mapped[Optional[str]] = mapped_column(Text)
    #: Addresses the client may call from (comma-separated CIDRs; empty: anywhere).
    allowed_cidrs: Mapped[Optional[str]] = mapped_column(String(2000))
    #: Where events are sent (https only), and the secret they are signed with (encrypted at rest).
    webhook_url: Mapped[Optional[str]] = mapped_column(String(500))
    webhook_secret: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: When the credentials last changed (secret rotated, keys replaced): tokens
    #: issued before are refused.
    credentials_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class IntegrationAssertion(Base):
    """A client assertion's ``jti``, kept until the assertion expires: each is used once."""

    __tablename__ = "integration_assertions"
    __table_args__ = (UniqueConstraint("client_pk", "jti", name="uq_integration_assertion_jti"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False,
                                             index=True)
    client_pk: Mapped[str] = mapped_column(ForeignKey("integration_clients.id", ondelete="CASCADE"), nullable=False)
    jti: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IntegrationRequest(Base):
    """One call to the integration API: no bodies, no clinical data. Kept 30 days."""

    __tablename__ = "integration_requests"
    __table_args__ = (Index("ix_integration_requests_client_at", "client_pk", "at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False,
                                             index=True)
    client_pk: Mapped[str] = mapped_column(ForeignKey("integration_clients.id", ondelete="CASCADE"), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    #: The path only (never the query string).
    path: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    ip: Mapped[Optional[str]] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class IntegrationResource(Base):
    """A FHIR resource a client sent (by its id), and the record it became:
    sending it again with another meta.versionId (or other content) corrects
    the record (a new version)."""

    __tablename__ = "integration_resources"
    __table_args__ = (UniqueConstraint("client_pk", "resource_type", "resource_id",
                                       name="uq_integration_resource"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False,
                                             index=True)
    client_pk: Mapped[str] = mapped_column(ForeignKey("integration_clients.id", ondelete="CASCADE"), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version_id: Mapped[Optional[str]] = mapped_column(String(64))
    #: sha256 of the resource as sent (tells an unchanged resource from a correction).
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_id: Mapped[str] = mapped_column(ForeignKey("clinical_records.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow,
                                                 onupdate=utcnow)


class IntegrationIdempotency(Base):
    """The answer to a request sent with an Idempotency-Key, replayed when the
    same key comes again (for a day). The answer is encrypted at rest."""

    __tablename__ = "integration_idempotency"
    __table_args__ = (UniqueConstraint("client_pk", "key", name="uq_integration_idempotency_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False,
                                             index=True)
    client_pk: Mapped[str] = mapped_column(ForeignKey("integration_clients.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    #: sha256 of the method, path and body: the same key with another request is refused.
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class WebhookDelivery(Base):
    """An event for a client's webhook, sent by the worker with retries. The
    body (encrypted at rest) is deleted once delivered or given up."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),
                      Index("ix_webhook_deliveries_client", "client_pk", "created_at"))

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False,
                                             index=True)
    client_pk: Mapped[str] = mapped_column(ForeignKey("integration_clients.id", ondelete="CASCADE"), nullable=False)
    event_id: Mapped[str] = mapped_column(String(40), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=DeliveryStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[Optional[int]] = mapped_column(Integer)
    last_error: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# The encrypted columns are encrypted on flush and decrypted on load.
from app import sealing  # noqa: E402,F401  (registers the ORM events)
