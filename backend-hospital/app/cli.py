"""Operator commands.

    python -m app.cli bootstrap --code SPH --name "St. Paul's Millennium Medical Center" \
        --admin-email admin@example.com --admin-name "Admin User"

creates a hospital and its first admin, and prints a one-time password.
"""

from __future__ import annotations

import argparse
import sys

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select

from app.db import session_scope
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
    with session_scope() as session:
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
    commands.add_parser("hospitals", help="list hospitals and their status")
    args = parser.parse_args(argv)

    if args.command in ("approve", "suspend"):
        from app.api.onboarding import set_status
        from app.models import HospitalStatus

        with session_scope() as session:
            hospital = session.scalar(select(Hospital).where(Hospital.code == args.code.strip().upper()))
            if hospital is None:
                raise SystemExit(f"No hospital with code {args.code}.")
            hospital_id = hospital.id
        result = set_status(hospital_id, HospitalStatus.APPROVED if args.command == "approve" else HospitalStatus.SUSPENDED)
        print(f"{result['code']}: {result['status']}" + ("" if result["listed"] else
              f" (not listed yet; missing {', '.join(result['missing_for_listing'])})"))
        return 0
    if args.command == "hospitals":
        with session_scope() as session:
            for h in session.scalars(select(Hospital).order_by(Hospital.created_at)):
                print(f"{h.code:8} {h.status:10} {h.name}")
        return 0

    if args.command == "bootstrap":
        password = bootstrap(args.code, args.name, args.name_am, args.admin_email, args.admin_name)
        print(f"Hospital {args.code.strip().upper()} created. "
              f"Admin {args.admin_email.strip().lower()} one-time password: {password}")
        print("The admin must change it at first sign-in.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
