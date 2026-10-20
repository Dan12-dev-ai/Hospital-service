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
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.getcwd())

from sqlalchemy import select  # noqa: E402

from app import bookings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import Booking, Hospital, HospitalStatus, ProcessedEvent, StaffUser  # noqa: E402
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


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["hospital"] and len(args) >= 2:
        print(json.dumps(seed_hospital(args[1], "--unlisted" in args[2:])))
    elif args[:1] == ["booking"] and len(args) == 5:
        print(json.dumps(seed_booking(args[1], args[2], int(args[3]), args[4])))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
