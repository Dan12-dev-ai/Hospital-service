"""Test data for the browser tests, written straight into the e2e database.

Run with backend-hospital as the working directory and the same
HOSPITAL_DATABASE_URL as the server under test. Prints JSON.

    python seed.py hospital <tag> [--unlisted]
        An approved hospital with an administrator, a developer and a nurse
        (a clinical role, refused at sign-in), plus "newdev", a developer who
        must change a temporary password. Listed (price and location) unless
        --unlisted.

    python seed.py prices <hospital_id>
        A price list, as the hospital's system would sync it (two lab tests,
        one imaging study).

    python seed.py applicant <tag> [--complete] [--submitted] [--no-price] [--demo]
        A hospital applying to join Endod (pending), with its admin (the
        contact person, with a mobile). --complete fills in every step but
        the demo (facility with its in-person price, location, the four
        documents as small PDFs); --submitted also books the first free demo
        slot and submits. --no-price leaves the price out (a draft saved
        before the wizard asked for it); --demo books the demo without submitting.
        Each applicant's contact has its own mobile (one demo per number).

    python seed.py applicant-staff <hospital_id> <email> <role>
        Another staff member of an applying hospital, with the temporary
        password (they must change it at first sign-in).

    python seed.py totp-code <email>
        A code from the account's authenticator app, for a step no earlier
        code used (waiting for the next step if needed). The accounts of a
        seeded hospital have an authenticator set up already (but newdev,
        who sets it up after changing the temporary password).
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.getcwd())

from sqlalchemy import select  # noqa: E402

from app import totp  # noqa: E402
from app.db import platform_session  # noqa: E402
from app.models import Hospital, HospitalStatus, PriceItem, StaffUser  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "E2e-Password-1"
TEMPORARY_PASSWORD = "Temporary-Pass-1"
ROLES = {
    "admin": "admin",
    "developer": "developer",
    # A clinical role of the old portal: refused at sign-in.
    "nurse": "nurse",
}


def seed_hospital(tag: str, unlisted: bool) -> dict:
    code = tag.upper()[:12]
    with platform_session() as session:
        hospital = Hospital(
            code=code, name=f"{tag.title()} General Hospital", kind="private", city="Addis Ababa",
            status=HospitalStatus.APPROVED, timezone="Africa/Addis_Ababa",
        )
        if not unlisted:
            hospital.latitude, hospital.longitude = 9.0320, 38.7469
            hospital.price_in_person = 15000
        session.add(hospital)
        session.flush()
        hashed = hash_password(PASSWORD)
        accounts = {}
        for key, role in ROLES.items():
            email = f"{key}@{tag}.example"
            name = f"{key.title()} {tag.title()}"
            # Two-step verification set up already (app/twofactor.py): the
            # tests read codes with `seed.py totp-code`.
            session.add(StaffUser(hospital_id=hospital.id, email=email, full_name=name, role=role,
                                  password_hash=hashed, must_change_password=False,
                                  totp_secret=totp.new_secret(), totp_enrolled_at=datetime.now(timezone.utc)))
            accounts[key] = {"email": email, "name": name}
        email = f"newdev@{tag}.example"
        session.add(StaffUser(hospital_id=hospital.id, email=email, full_name=f"Newdev {tag.title()}",
                              role="developer", password_hash=hash_password(TEMPORARY_PASSWORD),
                              must_change_password=True))
        accounts["newdev"] = {"email": email, "name": f"Newdev {tag.title()}"}
        session.flush()
        return {"hospital_id": hospital.id, "name": hospital.name, "password": PASSWORD,
                "temporary_password": TEMPORARY_PASSWORD, "accounts": accounts}


def seed_prices(hospital_id: str) -> dict:
    rows = [("lab_tests", "CBC", "Complete blood count", 35000), ("lab_tests", "MAL-RDT", "Malaria rapid test", 12000),
            ("imaging", "XR-CHEST", "Chest X-ray", 45000)]
    with platform_session() as session:
        for category, code, name, price in rows:
            session.add(PriceItem(hospital_id=hospital_id, category=category, code=code, name=name, price=price,
                                  active=True))
    return {"items": len(rows)}


def seed_applicant(tag: str, complete: bool, submitted: bool, price: bool = True, demo: bool = False) -> dict:
    from app import crypto, files, onboarding
    from app.db import new_id
    from app.models import (
        ApplicationStatus, DemoBooking, DocumentKind, OnboardingApplication, OnboardingDocument, Role,
    )

    code = tag.upper()[:12]
    email = f"apply@{tag}.example"
    with platform_session() as session:
        hospital = Hospital(code=code, name=f"{tag.title()} Applicant Clinic", kind="private", facility_type="clinic",
                            status=HospitalStatus.PENDING, timezone="Africa/Addis_Ababa")
        session.add(hospital)
        session.flush()
        admin = StaffUser(hospital_id=hospital.id, email=email, full_name="Abeba Applicant", role=Role.ADMIN,
                          phone="+2519" + str(int(uuid.uuid4().hex[:12], 16) % 10**8).zfill(8),
                          password_hash=hash_password(PASSWORD), must_change_password=False)
        session.add(admin)
        session.flush()
        application = OnboardingApplication(hospital_id=hospital.id, status=ApplicationStatus.DRAFT,
                                            contact_title="Clinic Manager")
        session.add(application)
        if complete or submitted:
            hospital.city, hospital.phone, hospital.open_hours = "Adama", "022 111 2233", "Mon-Fri 08:00-18:00"
            hospital.services = "general_medicine"
            if price:
                hospital.price_in_person = 15000
            hospital.address, hospital.latitude, hospital.longitude = "Main Street", 8.54, 39.27
            application.license_number = f"MOH/{code}/1"
            pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
            key = crypto.active_key(session, hospital.id)  # documents are encrypted at rest
            for kind in DocumentKind.ALL:
                file_id = new_id()
                size, sha256, content_type = files.store_bytes(pdf, hospital.id, file_id, key)
                session.add(OnboardingDocument(id=file_id, hospital_id=hospital.id, kind=kind, filename=f"{kind}.pdf",
                                               content_type=content_type, size=size, sha256=sha256,
                                               key_version=key.version, uploaded_by=admin.id))
        demo_at = None
        if submitted or demo:
            taken = onboarding.taken_slots(session)
            slot = next(s for s in onboarding.slot_grid() if s.astimezone(timezone.utc) not in taken)
            session.add(DemoBooking(id=new_id(), hospital_id=hospital.id, slot_start=slot.astimezone(timezone.utc),
                                    phone=admin.phone))
            demo_at = slot.isoformat()
        if submitted:
            application.status = ApplicationStatus.SUBMITTED
            application.submitted_at = datetime.now(timezone.utc)
        return {"hospital_id": hospital.id, "name": hospital.name, "email": email, "password": PASSWORD,
                "demo_at": demo_at}


def seed_applicant_staff(hospital_id: str, email: str, role: str) -> dict:
    with platform_session() as session:
        user = StaffUser(hospital_id=hospital_id, email=email, full_name="Staff Member", role=role,
                         password_hash=hash_password(TEMPORARY_PASSWORD), must_change_password=True)
        session.add(user)
        session.flush()
        return {"id": user.id, "email": email, "temporary_password": TEMPORARY_PASSWORD}


def totp_code(email: str) -> dict:
    with platform_session() as session:
        user = session.scalar(select(StaffUser).where(StaffUser.email == email.strip().lower()))
        if user is None or not user.totp_secret:
            raise SystemExit(f"{email} has no authenticator set up")
        secret, last = user.totp_secret, user.totp_last_step
    now = totp.current_step()
    step = max(now, -1 if last is None else last + 1)
    if step > now + totp.WINDOW:
        # Every usable step was used: wait until this one is within reach.
        time.sleep(max(0.0, (step - totp.WINDOW) * totp.INTERVAL - time.time() + 0.2))
    return {"code": totp.code_at(secret, step)}


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["hospital"] and len(args) >= 2:
        print(json.dumps(seed_hospital(args[1], "--unlisted" in args[2:])))
    elif args[:1] == ["prices"] and len(args) == 2:
        print(json.dumps(seed_prices(args[1])))
    elif args[:1] == ["applicant"] and len(args) >= 2:
        print(json.dumps(seed_applicant(args[1], "--complete" in args[2:], "--submitted" in args[2:],
                                        price="--no-price" not in args[2:], demo="--demo" in args[2:])))
    elif args[:1] == ["applicant-staff"] and len(args) == 4:
        print(json.dumps(seed_applicant_staff(args[1], args[2], args[3])))
    elif args[:1] == ["totp-code"] and len(args) == 2:
        print(json.dumps(totp_code(args[1])))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
