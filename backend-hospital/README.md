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
| Linking to Endod | `GET`/`POST`/`DELETE /patients/{id}/link` |
| Records and visits | `GET`/`POST /patients/{id}/records`, `POST /patients/{id}/uploads` (one file as the body), `PATCH /records/{id}` (correction), `POST /records/{id}/retract`, `GET /records/{id}/files/{file_id}`, `GET`/`POST /patients/{id}/visits`, `PATCH /visits/{id}` (follow-up) |
| Queues | `GET /queue?day=`, `POST /queue/check-in`, `POST /queue/{doctor_id}/call-next`, `POST /queue/entries/{id}/done|skip|cancel` |
| Shared with us | `GET /shared?patient_id=`, `GET /shared/{share_id}/files/{file_id}` |
| Imports | `POST /imports/preview` (the file as the body), `POST /imports/{id}/confirm`, `GET /imports/template.csv` |
| Joining Endod (a pending hospital's admin) | `POST /onboarding` (public: the account), `GET /onboarding/application`, `PATCH /onboarding/contact|facility|location|documents`, `POST`/`GET /onboarding/documents/{kind}` (one file as the body), `GET /onboarding/demo-slots`, `POST /onboarding/demo`, `POST /onboarding/submit` |
| Endod platform only (`X-Platform-Key`) | `GET /platform/records/{record_id}/files/{file_id}`; `GET /platform/hospitals`, `POST /platform/hospitals/{id}/approve|suspend|reject`, `DELETE /platform/hospitals/{id}`; `GET /platform/applications?status=`, `GET /platform/applications/{hospital_id}`, `GET /platform/applications/{hospital_id}/documents/{kind}` |

- **Joining Endod** (`app/onboarding.py`): a hospital or clinic applies
  through the portal's wizard: the contact person's account first, then the
  facility, its location, four required documents (Ministry of Health
  license, trade license, TIN certificate, the owner's or manager's ID; PDF or
  image, 10 MB each) with the license number, and a 30-minute demo with Endod
  (weekdays 09:00 to 17:00 Addis Ababa time, tomorrow to 30 days ahead, one
  hospital per slot). Each step is saved, so the wizard resumes where it
  stopped. Until Endod approves the *application* (whatever the hospital's
  status: a suspended applicant stays locked), every staff route but sign-in,
  sign-out, the password change and `/onboarding/*` answers 403; staff other
  than the contact person see only `GET /onboarding/status`. A demo needs the
  four documents, one mobile holds one demo, and a booking is released if the
  application is not submitted within 24 hours, or is sent back or suspended.
  Booking or moving the demo emits `onboarding.demo_booked`
  ([docs/events.md](../docs/events.md)) so the platform texts the contact
  person. Endod reviews with `python -m app.cli applications`,
  `python -m app.cli application --code X` (details and the documents' paths)
  and `approve --code X` (a submitted application only; `--force` overrides
  that and is written to the audit log), or the platform API; a rejection carries a reason
  the hospital sees, and it can fix and resubmit.

- **Patients** get a hospital number when registered (`SPH-000124`, per
  hospital, never reused) and can carry their Endod ID (`DE482731`), unique
  within the hospital, stored only once Endod confirms the link. Search covers name (English or Amharic), hospital
  number, Endod ID and phone. Phones are stored as `+251XXXXXXXXX`; an age
  can stand in for an unknown date of birth. Registering the same name and
  phone twice needs `confirm_duplicate`. Reception and records staff edit
  identity and payer details (cash, CBHI, private, credit); doctors and
  nurses move the patient through care (`opd`, `emergency`, `admitted`,
  `discharge`, `discharged`), assign the ward, bed and attending doctor, and
  record allergy and risk alerts. Admission checks the ward's bed capacity
  and that the bed is free. Opening a patient's record is written to the
  audit log.
- **Patient history** ([docs/history-events.md](../docs/history-events.md)):
  linking to Endod (health card QR, or Endod ID and phone), clinical records
  with PDF/image files (kept under `HOSPITAL_FILES_DIR`, type checked by
  content), visits and follow-ups, per-doctor queues, records patients share
  with the hospital, and FHIR/CSV imports ([docs/imports.md](../docs/imports.md)).
  Records reach the patient's Endod app only once the patient is linked.
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
