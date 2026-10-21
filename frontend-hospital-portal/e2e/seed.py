"""Test data for the browser tests, written straight into the e2e database.

Run with backend-hospital as the working directory and the same
HOSPITAL_DATABASE_URL as the server under test. Prints JSON.

    python seed.py hospital <tag> [--unlisted]
        An approved hospital with one account per role (admin, doctor,
        doctor2, nurse, reception, billing) plus "newdoc", a doctor who must
        change a temporary password. Listed (price, location, video visits)
        unless --unlisted.

    python seed.py booking <hospital_id> <in_person|video> <minutes_from_now> <patient name>
        A patient's booking arriving from the Endod app: the
        appointment.requested event handled the way the worker handles it
        (app.bookings.on_requested inside one session, with the event id
        recorded as processed).

    python seed.py link-reply <patient_id> <linked|refused> [reason]
        Endod's answer to the patient's pending link request: the
        patient.linked / patient.link_refused event handled as the worker would.

    python seed.py link <patient_id> <dedan_id>
        The patient linked to Endod already (as after a confirmed request).

    python seed.py queue-yesterday <hospital_id> <doctor email> <patient name>
        A walk-in checked in to the doctor's queue yesterday, still waiting.

    python seed.py share <hospital_id> <dedan_id> <patient name> <record title>
        A patient sharing one record (with a PDF) with the hospital: the
        records.shared event handled as the worker would.

    python seed.py applicant <tag> [--complete] [--submitted]
        A hospital applying to join Endod (pending), with its admin (the
        contact person, with a mobile). --complete fills in every step but
        the demo (facility, location, the four documents as small PDFs);
        --submitted also books the first free demo slot and submits.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.getcwd())

from sqlalchemy import select  # noqa: E402

from app import bookings, linking, records, sharing  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import (  # noqa: E402
    Booking, Hospital, HospitalStatus, LinkStatus, Patient, PatientLinkRequest, ProcessedEvent, StaffUser,
)
from app.security import hash_password  # noqa: E402

PASSWORD = "E2e-Password-1"
TEMPORARY_PASSWORD = "Temporary-Pass-1"
ROLES = {
    "admin": "admin",
    "doctor": "doctor",
    "doctor2": "doctor",
    "nurse": "nurse",
    "reception": "reception",
    "billing": "billing",
    "records": "records",
}


def seed_hospital(tag: str, unlisted: bool) -> dict:
    code = tag.upper()[:12]
    with session_scope() as session:
        hospital = Hospital(
            code=code, name=f"{tag.title()} General Hospital", kind="private", city="Addis Ababa",
            status=HospitalStatus.APPROVED, timezone="Africa/Addis_Ababa",
        )
        if not unlisted:
            hospital.latitude, hospital.longitude = 9.0320, 38.7469
            hospital.price_in_person, hospital.price_video = 15000, 12000
            hospital.video_enabled = True
        session.add(hospital)
        session.flush()
        hashed = hash_password(PASSWORD)
        accounts = {}
        for key, role in ROLES.items():
            email = f"{key}@{tag}.example"
            name = f"{'Dr. ' if role == 'doctor' else ''}{key.title()} {tag.title()}"
            session.add(StaffUser(hospital_id=hospital.id, email=email, full_name=name, role=role,
                                  password_hash=hashed, must_change_password=False))
            accounts[key] = {"email": email, "name": name}
        email = f"newdoc@{tag}.example"
        session.add(StaffUser(hospital_id=hospital.id, email=email, full_name=f"Dr. Newdoc {tag.title()}",
                              role="doctor", password_hash=hash_password(TEMPORARY_PASSWORD),
                              must_change_password=True))
        accounts["newdoc"] = {"email": email, "name": f"Dr. Newdoc {tag.title()}"}
        session.flush()
        return {"hospital_id": hospital.id, "name": hospital.name, "password": PASSWORD,
                "temporary_password": TEMPORARY_PASSWORD, "accounts": accounts}


def seed_booking(hospital_id: str, mode: str, minutes: int, patient: str) -> dict:
    appointment_id = f"apt-{uuid.uuid4().hex[:16]}"
    payload = {
        "appointment_id": appointment_id,
        "hospital_id": hospital_id,
        "patient": {"dedan_id": f"DE-{uuid.uuid4().int % 1_000_000:06d}", "name": patient, "phone": "+251911234567"},
        "visit_mode": mode,
        "service": "general_medicine",
        "scheduled_at": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(),
        "duration_minutes": 30,
        "notes": "Booked in the Endod app",
        "price": 12000 if mode == "video" else 15000,
    }
    event_id = uuid.uuid4().hex
    # As app.eventbus does for each event from the patient platform.
    with session_scope() as session:
        bookings.on_requested(session, payload)
        session.add(ProcessedEvent(id=event_id, type="appointment.requested"))
    with session_scope() as session:
        booking = session.scalar(select(Booking).where(Booking.external_id == appointment_id))
        if booking is None:
            raise SystemExit(f"booking was not accepted: {payload}")
        return {"id": booking.id, "status": booking.status, "dedan_id": payload["patient"]["dedan_id"]}


def handle(event_type: str, handler, payload: dict) -> None:
    """As app.eventbus does for each event from the patient platform."""
    with session_scope() as session:
        handler(session, payload)
        session.add(ProcessedEvent(id=uuid.uuid4().hex, type=event_type))


def link_reply(patient_id: str, answer: str, reason: str) -> dict:
    with session_scope() as session:
        request = session.scalar(select(PatientLinkRequest).where(
            PatientLinkRequest.patient_id == patient_id, PatientLinkRequest.status == LinkStatus.PENDING))
        if request is None:
            raise SystemExit("no pending link request")
        patient = session.get(Patient, patient_id)
        payload = {"request_id": request.id, "hospital_id": request.hospital_id, "patient_id": patient_id,
                   "dedan_id": request.dedan_id}
        name = patient.full_name
    if answer == "linked":
        handle("patient.linked", linking.on_linked, {**payload, "name": name, "phone": "+251911234567"})
    else:
        handle("patient.link_refused", linking.on_refused, {**payload, "reason": reason or "not_verified"})
    return {"request_id": payload["request_id"], "dedan_id": payload["dedan_id"]}


def link_now(patient_id: str, dedan_id: str) -> dict:
    with session_scope() as session:
        patient = session.get(Patient, patient_id)
        linking.link(session, patient, dedan_id, records.hospital_today(session, patient.hospital_id))
        return {"patient_id": patient.id, "dedan_id": patient.dedan_id}


def share(hospital_id: str, dedan_id: str, patient: str, title: str) -> dict:
    share_id, record_id, file_id = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
    handle("records.shared", sharing.on_shared, {
        "share_id": share_id, "hospital_id": hospital_id, "dedan_id": dedan_id, "patient_name": patient,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "records": [{
            "record_id": record_id, "origin": "Tikur Anbessa Hospital", "category": "lab_result", "title": title,
            "details": {"items": [{"test": "Hemoglobin", "value": "13.1", "unit": "g/dL", "flag": "normal"}]},
            "occurred_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
            "recorded_by": "Dr. Selam Haile",
            "files": [{"file_id": file_id, "filename": "cbc.pdf", "content_type": "application/pdf",
                       "size": 1234, "sha256": "0" * 64}],
        }],
    })
    return {"share_id": share_id, "record_id": record_id, "file_id": file_id}


def queue_yesterday(hospital_id: str, doctor_email: str, patient: str) -> dict:
    """A walk-in checked in yesterday (hospital time) and still waiting."""
    from datetime import timedelta as days

    from app import queues

    with session_scope() as session:
        doctor = session.scalar(select(StaffUser).where(StaffUser.email == doctor_email))
        yesterday = records.hospital_today(session, hospital_id) - days(days=1)
        queue = queues.lock_queue(session, hospital_id, doctor.id, yesterday)
        entry = queues.check_in(session, queue, patient_name=patient, phone="+251911000009", dedan_id=None,
                                patient_id=None, booking_id=None, staff_id=None)
        return {"entry_id": entry.id, "ticket": entry.ticket, "day": yesterday.isoformat()}


def seed_applicant(tag: str, complete: bool, submitted: bool) -> dict:
    from app import files, onboarding
    from app.db import new_id
    from app.models import (
        ApplicationStatus, DemoBooking, DocumentKind, OnboardingApplication, OnboardingDocument, Role,
    )

    code = tag.upper()[:12]
    email = f"apply@{tag}.example"
    with session_scope() as session:
        hospital = Hospital(code=code, name=f"{tag.title()} Applicant Clinic", kind="private", facility_type="clinic",
                            status=HospitalStatus.PENDING, timezone="Africa/Addis_Ababa")
        session.add(hospital)
        session.flush()
        admin = StaffUser(hospital_id=hospital.id, email=email, full_name="Abeba Applicant", role=Role.ADMIN,
                          phone="+251911000123", password_hash=hash_password(PASSWORD), must_change_password=False)
        session.add(admin)
        session.flush()
        application = OnboardingApplication(hospital_id=hospital.id, status=ApplicationStatus.DRAFT,
                                            contact_title="Clinic Manager")
        session.add(application)
        if complete or submitted:
            hospital.city, hospital.phone, hospital.open_hours = "Adama", "022 111 2233", "Mon-Fri 08:00-18:00"
            hospital.services = "general_medicine"
            hospital.address, hospital.latitude, hospital.longitude = "Main Street", 8.54, 39.27
            application.license_number = f"MOH/{code}/1"
            pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
            for kind in DocumentKind.ALL:
                file_id = new_id()
                size, sha256, content_type = files.store_bytes(pdf, hospital.id, file_id)
                session.add(OnboardingDocument(id=file_id, hospital_id=hospital.id, kind=kind, filename=f"{kind}.pdf",
                                               content_type=content_type, size=size, sha256=sha256,
                                               uploaded_by=admin.id))
        demo_at = None
        if submitted:
            taken = onboarding.taken_slots(session)
            slot = next(s for s in onboarding.slot_grid() if s.astimezone(timezone.utc) not in taken)
            session.add(DemoBooking(id=new_id(), hospital_id=hospital.id, slot_start=slot.astimezone(timezone.utc)))
            application.status = ApplicationStatus.SUBMITTED
            application.submitted_at = datetime.now(timezone.utc)
            demo_at = slot.isoformat()
        return {"hospital_id": hospital.id, "name": hospital.name, "email": email, "password": PASSWORD,
                "demo_at": demo_at}


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["hospital"] and len(args) >= 2:
        print(json.dumps(seed_hospital(args[1], "--unlisted" in args[2:])))
    elif args[:1] == ["booking"] and len(args) == 5:
        print(json.dumps(seed_booking(args[1], args[2], int(args[3]), args[4])))
    elif args[:1] == ["link-reply"] and len(args) in (3, 4):
        print(json.dumps(link_reply(args[1], args[2], args[3] if len(args) == 4 else "")))
    elif args[:1] == ["link"] and len(args) == 3:
        print(json.dumps(link_now(args[1], args[2])))
    elif args[:1] == ["queue-yesterday"] and len(args) == 4:
        print(json.dumps(queue_yesterday(args[1], args[2], args[3])))
    elif args[:1] == ["applicant"] and len(args) >= 2:
        print(json.dumps(seed_applicant(args[1], "--complete" in args[2:], "--submitted" in args[2:])))
    elif args[:1] == ["share"] and len(args) == 5:
        print(json.dumps(share(args[1], args[2], args[3], args[4])))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
