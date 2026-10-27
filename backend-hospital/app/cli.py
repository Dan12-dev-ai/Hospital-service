"""Operator commands (they act for Endod across hospitals: platform scope).

    python -m app.cli bootstrap --code SPH --name "St. Paul's Millennium Medical Center" \
        --admin-email admin@example.com --admin-name "Admin User"

creates a hospital and its first admin, and prints a one-time password.

    python -m app.cli applications              # hospitals applying to join Endod
    python -m app.cli application --code TASH   # one application, with its documents' paths
    python -m app.cli approve --code TASH
"""

from __future__ import annotations

import argparse
import sys

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select

from app.db import platform_session
from app.models import Hospital, Role, StaffUser
from app.security import hash_password, temporary_password


def bootstrap(code: str, name: str, name_am: str | None, admin_email: str, admin_name: str) -> str:
    code = code.strip().upper()
    name, admin_name = name.strip(), admin_name.strip()
    name_am = (name_am or "").strip() or None
    if not code.isalnum() or not 2 <= len(code) <= 12:
        raise SystemExit("--code must be 2-12 letters or digits, e.g. SPH.")
    if len(name) < 2 or len(admin_name) < 2:
        raise SystemExit("--name and --admin-name must not be blank.")
    try:
        admin_email = validate_email(admin_email.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise SystemExit(f"--admin-email is not a valid email: {exc}") from exc
    with platform_session() as session:
        if session.scalar(select(Hospital).where(Hospital.code == code)) is not None:
            raise SystemExit(f"A hospital with code {code} already exists.")
        if session.scalar(select(StaffUser).where(StaffUser.email == admin_email)) is not None:
            raise SystemExit(f"An account with email {admin_email} already exists.")
        hospital = Hospital(code=code, name=name, name_am=name_am)
        session.add(hospital)
        session.flush()
        password = temporary_password()
        session.add(StaffUser(
            hospital_id=hospital.id, email=admin_email, full_name=admin_name, role=Role.ADMIN,
            password_hash=hash_password(password), must_change_password=True,
        ))
    return password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    boot = commands.add_parser("bootstrap", help="create a hospital and its first admin")
    boot.add_argument("--code", required=True, help="short code, e.g. SPH (used in hospital numbers)")
    boot.add_argument("--name", required=True)
    boot.add_argument("--name-am")
    boot.add_argument("--admin-email", required=True)
    boot.add_argument("--admin-name", required=True)
    for name, help_text in (("approve", "list a hospital in the Endod app"), ("suspend", "take a hospital off the Endod app")):
        cmd = commands.add_parser(name, help=help_text)
        cmd.add_argument("--code", required=True, help="the hospital's code, e.g. SPH")
        if name == "approve":
            cmd.add_argument("--force", action="store_true",
                             help="approve even though the application is not submitted (written to the audit log)")
    commands.add_parser("hospitals", help="list hospitals and their status")
    commands.add_parser("applications", help="list onboarding applications (status, submitted, demo)")
    detail = commands.add_parser("application", help="show one application and where its documents are")
    detail.add_argument("--code", required=True, help="the hospital's code, e.g. TASH")
    args = parser.parse_args(argv)

    if args.command == "applications":
        return list_applications()
    if args.command == "application":
        return show_application(args.code)

    if args.command in ("approve", "suspend"):
        from app.api.onboarding import set_status
        from app.models import HospitalStatus

        with platform_session() as session:
            hospital = session.scalar(select(Hospital).where(Hospital.code == args.code.strip().upper()))
            if hospital is None:
                raise SystemExit(f"No hospital with code {args.code}.")
            hospital_id = hospital.id
        from fastapi import HTTPException

        try:
            result = set_status(hospital_id,
                                HospitalStatus.APPROVED if args.command == "approve" else HospitalStatus.SUSPENDED,
                                force=getattr(args, "force", False))
        except HTTPException as exc:
            hint = " Use --force to approve it anyway." if args.command == "approve" and exc.status_code == 409 else ""
            raise SystemExit(f"{exc.detail}{hint}") from exc
        print(f"{result['code']}: {result['status']}" + ("" if result["listed"] else
              f" (not listed yet; missing {', '.join(result['missing_for_listing'])})"))
        return 0
    if args.command == "hospitals":
        with platform_session() as session:
            for h in session.scalars(select(Hospital).order_by(Hospital.created_at)):
                print(f"{h.code:8} {h.status:10} {h.name}")
        return 0

    if args.command == "bootstrap":
        password = bootstrap(args.code, args.name, args.name_am, args.admin_email, args.admin_name)
        print(f"Hospital {args.code.strip().upper()} created. "
              f"Admin {args.admin_email.strip().lower()} one-time password: {password}")
        print("The admin must change it at first sign-in.", file=sys.stderr)
    return 0


def list_applications() -> int:
    from app.api.application import list_applications as applications

    rows = applications(status_filter=None)
    if not rows:
        print("No applications.")
    for row in rows:
        demo = _addis(row["demo_at"]) if row["demo_at"] else "no demo booked"
        submitted = _addis(row["submitted_at"]) if row["submitted_at"] else "-"
        print(f"{row['code']:8} {row['status']:10} submitted {submitted:22} demo {demo:22} {row['name']}")
    return 0


def _addis(iso: str) -> str:
    from datetime import datetime

    from app.onboarding import DEMO_TZ

    return datetime.fromisoformat(iso).astimezone(DEMO_TZ).strftime("%a %d %b %Y %H:%M")


def show_application(code: str) -> int:
    from app import files
    from app.onboarding import application_payload

    with platform_session() as session:
        hospital = session.scalar(select(Hospital).where(Hospital.code == code.strip().upper()))
        if hospital is None:
            raise SystemExit(f"No hospital with code {code}.")
        app = application_payload(session, hospital)
        facility, location, contact = app["facility"], app["location"], app["contact"]
        print(f"{hospital.name} ({hospital.code}), id {hospital.id}")
        print(f"  status:      {app['status']} (hospital {app['hospital_status']})")
        print(f"  submitted:   {_addis(app['submitted_at']) if app['submitted_at'] else '-'}")
        if app["rejection_reason"]:
            print(f"  sent back:   {app['rejection_reason']}")
        print(f"  facility:    {facility['facility_type']}, {facility['ownership']}; {facility['city'] or '-'}; "
              f"phone {facility['phone'] or '-'}; hours {facility['open_hours'] or '-'}")
        print(f"  services:    {', '.join(facility['services']) or '-'}")
        print(f"  location:    {location['address'] or '-'} ({location['latitude']}, {location['longitude']})")
        print(f"  contact:     {contact['full_name']}, {contact['title'] or '-'}, {contact['phone'] or '-'}, "
              f"{contact['email']}")
        demo = app["demo"]
        print(f"  demo:        {_addis(demo['demo_at']) + ' Addis Ababa time' if demo else 'not booked'}")
        print(f"  license no.: {app['documents']['license_number'] or '-'}")
        from app.models import OnboardingDocument

        rows = {d.kind: d for d in session.scalars(
            select(OnboardingDocument).where(OnboardingDocument.hospital_id == hospital.id))}
        for item in app["documents"]["items"]:
            doc = rows.get(item["kind"])
            where = (f"{files.path_for(hospital.id, doc.id)}  ({doc.filename}, {doc.content_type}, "
                     f"{doc.size} bytes, sha256 {doc.sha256})") if doc else "MISSING"
            print(f"  {item['label']}: {where}")
        if app["next_step"] != "review":
            print(f"  still missing: {', '.join(f'{k}: {v}' for k, v in app['missing'].items() if v)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
