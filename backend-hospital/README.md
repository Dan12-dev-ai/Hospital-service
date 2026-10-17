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

- **Sessions:** `Authorization: Bearer <token>`. The token is random; only
  its SHA-256 is stored, so sessions can be ended (sign-out, password change,
  deactivation) and a database leak exposes no usable tokens.
- **Roles:** admin, doctor, nurse, reception, pharmacist, billing, records.
- **Accounts** are created by an admin with a one-time password that must be
  changed before anything else works. Eight failed sign-ins lock an account
  for 15 minutes.
- **Isolation:** every query is scoped to the signed-in staff member's hospital.
- **Errors** look like `{"error": "...", "error_code": "..."}`.

Next: patients and doctors, appointments, pharmacy, billing, reports, and the
link to the Endod patient platform.
