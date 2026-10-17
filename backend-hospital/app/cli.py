"""Operator commands.

    python -m app.cli bootstrap --code SPH --name "St. Paul's Millennium Medical Center" \
        --admin-email admin@example.com --admin-name "Admin User"

creates a hospital and its first admin, and prints a one-time password.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.db import session_scope
from app.models import Hospital, Role, StaffUser
from app.security import hash_password, temporary_password


def bootstrap(code: str, name: str, name_am: str | None, admin_email: str, admin_name: str) -> str:
    code = code.strip().upper()
    with session_scope() as session:
        if session.scalar(select(Hospital).where(Hospital.code == code)) is not None:
            raise SystemExit(f"A hospital with code {code} already exists.")
        if session.scalar(select(StaffUser).where(StaffUser.email == admin_email.lower())) is not None:
            raise SystemExit(f"An account with email {admin_email} already exists.")
        hospital = Hospital(code=code, name=name, name_am=name_am)
        session.add(hospital)
        session.flush()
        password = temporary_password()
        session.add(StaffUser(
            hospital_id=hospital.id, email=admin_email.lower(), full_name=admin_name, role=Role.ADMIN,
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
    args = parser.parse_args(argv)

    if args.command == "bootstrap":
        password = bootstrap(args.code, args.name, args.name_am, args.admin_email, args.admin_name)
        print(f"Hospital {args.code.upper()} created. Admin {args.admin_email} one-time password: {password}")
        print("The admin must change it at first sign-in.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
