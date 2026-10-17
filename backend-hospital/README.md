# Endod hospital service (backend)

The backend of the hospital staff portal (`../frontend-hospital-portal`).
It is a separate service with **its own database**: hospital staff, wards,
pharmacy stock, billing and reports live here. It exchanges data with the
Endod patient platform only through APIs, and patient data crosses over only
with the patient's consent.

## Run locally

```sh
python -m venv ../.venv && ../.venv/Scripts/pip install -r requirements-dev.txt   # or bin/ on Linux/macOS
cp .env.example .env            # defaults to SQLite (./hospital.db) if no URL is set
alembic upgrade head
python -m app.cli bootstrap --code SPH --name "St. Paul's Millennium Medical Center" \
    --admin-email admin@example.com --admin-name "Admin User"
uvicorn app.main:app --reload --port 8100
```

The bootstrap command prints a one-time password; the admin changes it at
first sign-in. API docs: http://localhost:8100/docs (outside production).

## Tests

```sh
python -m pytest tests -q
```

## What exists so far

| Area | Endpoints |
| --- | --- |
| Sign-in | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/password` |
| Hospital | `GET /hospital`, `PATCH /hospital` (admin) |
| Departments, wards, clinics, dispensaries | `GET /departments?kind=`, `POST /departments`, `PATCH /departments/{id}` (admin) |
| Staff accounts | `GET /staff`, `POST /staff`, `PATCH /staff/{id}`, `POST /staff/{id}/reset-password` (admin) |
| Patients | `GET /patients?q=&status=&department_id=&ward_id=&doctor_id=`, `GET /patients/stats`, `POST /patients`, `GET /patients/{id}`, `PATCH /patients/{id}`, `POST`/`DELETE /patients/{id}/alerts` |
| Doctors | `GET /doctors?q=&department_id=&rank=&status=`, `GET /doctors/{id}`, `PATCH /doctors/{id}/profile` (admin), `PATCH /doctors/{id}/duty` |

- **Patients** get a hospital number when registered (`SPH-000124`, per
  hospital, never reused) and can carry their Endod ID (`DE-482731`), unique
  within the hospital. Search covers name (English or Amharic), hospital
  number, Endod ID and phone. Phones are stored as `+251XXXXXXXXX`; an age
  can stand in for an unknown date of birth. Registering the same name and
  phone twice needs `confirm_duplicate`. Reception and records staff edit
  identity and payer details (cash, CBHI, private, credit); doctors and
  nurses move the patient through care (`opd`, `emergency`, `admitted`,
  `discharge`, `discharged`), assign the ward, bed and attending doctor, and
  record allergy and risk alerts. Admission checks the ward's bed capacity
  and that the bed is free. Opening a patient's record is written to the
  audit log.
- **Doctors** are staff with the doctor role. The directory shows licence,
  specialty, rank, extension, duty status (`on-duty`, `in-consultation`,
  `on-call`, `off-duty`) with location, and patient load against daily
  capacity. A doctor sets their own duty status; admins and nurses can set
  anyone's.

- **Sessions:** `Authorization: Bearer <token>`. The token is random; only
  its SHA-256 is stored, so sessions can be ended (sign-out, password change,
  deactivation) and a database leak exposes no usable tokens.
- **Roles:** admin, doctor, nurse, reception, pharmacist, billing, records.
- **Accounts** are created by an admin with a one-time password that must be
  changed before anything else works. Eight failed sign-ins lock an account
  for 15 minutes.
- **Isolation:** every query is scoped to the signed-in staff member's hospital.
- **Errors** look like `{"error": "...", "error_code": "..."}`.

Next: appointments, pharmacy, billing, reports, and the
link to the Endod patient platform.
