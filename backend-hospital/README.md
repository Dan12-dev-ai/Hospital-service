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
# On PostgreSQL (as CI does): the URL is the owner's; the tests create the
# hospital_app role and run the app as it, under row-level security.
HOSPITAL_TEST_DATABASE_URL=postgresql+psycopg://hospital:pw@localhost:5432/hospital python -m pytest tests -q
```

## Row-level security (PostgreSQL)

A second wall between hospitals, in the database (`app/rls.py`, migration
0007): even a query that forgets its `hospital_id` filter sees and writes only
its own hospital's rows.

- **Roles.** `hospital` owns the database and runs the migrations (the
  one-shot `migrate` service). The API and the worker log in as
  `hospital_app`: not a superuser, no BYPASSRLS, owns nothing, no DDL, and
  the audit log is SELECT and INSERT only. `hospital_platform` (NOLOGIN)
  acts for Endod across hospitals; `hospital_app` is a member without
  INHERIT, so it has none of its rights until a transaction runs
  `SET LOCAL ROLE hospital_platform`. `migrations/env.py` creates
  `hospital_app` when `HOSPITAL_APP_DB_PASSWORD` is set (or sets its password
  and attributes again) and grants it after every upgrade, on a new and an
  existing database alike; without the role the migration fails.
- **Refusal at start.** The API and the worker refuse to start when their
  login is a superuser, has BYPASSRLS or owns the tables.
- **Tenant per transaction.** `session_scope(staff.hospital_id)` sets
  `app.hospital_id` for its transaction only (`set_config(..., true)`, i.e.
  `SET LOCAL`, in an `after_begin` hook, so it never reaches the next user of
  a pooled connection). Every staff route passes the signed-in staff
  member's hospital.
- **Platform scope.** `platform_session()` is the only place that takes the
  `hospital_platform` role: `/platform/...` routes (X-Platform-Key), events
  from the bus (`eventbus._handle`), the worker's chores and expiries, and the
  CLI. No setting (GUC) opens anything: only that role has the
  `platform_access` policy.
- **Narrow lookups.** What must look past one hospital outside a platform
  transaction goes through SECURITY DEFINER functions owned by
  `hospital_platform`, with `search_path = public, pg_temp`, EXECUTE revoked
  from PUBLIC and granted to `hospital_app`, returning only what is needed:
  `hospital_of_staff_email` (sign-in; nothing for an inactive account),
  `hospital_of_session_token` (every request; nothing for a revoked or
  expired session or an inactive account), `hospital_code_taken` (sign-up),
  `demo_slots_taken` and `demo_phone_taken` (slot times, yes or no) and
  `release_stale_demo_bookings` (one fixed delete). The transaction then
  takes the hospital it learnt and reads everything else under the
  policies. The public sign-up never opens a platform transaction: it
  generates the new hospital's id first and uses it as the tenant.
- **Policies.** ENABLE and FORCE on 22 tables, each with `tenant_isolation`
  (`USING (hospital_id = current_setting('app.hospital_id', true))` and the
  same WITH CHECK) and `platform_access` (`TO hospital_platform`):
  `hospitals` (by `id`), `departments`, `staff_users`, `audit_events`,
  `doctor_profiles`, `patients`, `bookings`, `patient_link_requests`,
  `visits`, `clinical_records`, `record_files`, `queue_days`,
  `queue_entries`, `record_shares`, `import_batches`,
  `onboarding_applications`, `onboarding_documents`, `demo_bookings`,
  `prescription_dispenses`. The three tables without `hospital_id`
  (`patient_alerts`, `staff_sessions`, `shared_records`) are covered through
  their parent (`EXISTS` on `patients`, `staff_users`, `record_shares`, under
  their own policies): no new column or backfill, and a child can never
  disagree with its parent. `outbox_events` and `processed_events` belong to
  no hospital.
- **Same-hospital references.** Foreign keys ignore row security, so 29
  composite keys `(hospital_id, x) -> parent (hospital_id, id)` (with
  `UNIQUE (hospital_id, id)` on the parents) make a record, file, visit,
  queue entry, dispense... refer only to rows of its own hospital, with the
  same ON DELETE as the plain key (`SET NULL (x)` keeps `hospital_id`).
- **Fails closed.** With no tenant, every policy table reads as empty and
  every write is refused.
- **Limits.** This guards against mistakes in the app's queries. SQL injected
  into a query as `hospital_app` could still `set_config` another hospital,
  or with a second statement `SET ROLE hospital_platform`; the queries are
  parameterised (SQLAlchemy) to keep that out.
- The owner `hospital` is the container's superuser and is not subject to
  the policies, so migrations and `pg_dump -U hospital` (the backups) see
  everything as before.

### Deploying it to the existing production database

The migration changes no rows; it adds a role, keys, policies and functions.
It checks the existing rows against the new same-hospital keys: if a
cross-hospital reference already exists, it fails and changes nothing (the
copy test shows this first).

1. Test on a copy of production first (below).
2. Add to `/opt/endod-hospital/deploy/.env`:
   `APP_DB_PASSWORD=$(openssl rand -hex 32)` (hex: it goes into a URL).
3. `cd /opt/endod-hospital && git pull` (this branch, once merged), then
   `cd deploy && docker compose --env-file .env up -d --build`. The `migrate`
   service runs first as `hospital`: migration 0007 (which creates
   `hospital_platform`), then it creates `hospital_app` with that password
   and grants it. The API and worker start after it, connecting as
   `hospital_app`.
4. Check: `docker compose logs migrate` ends with `0006 -> 0007`;
   `docker compose exec postgres psql -U hospital -d hospital -c "select rolname, rolsuper, rolbypassrls from pg_roles where rolname = 'hospital_app'"`
   shows `f | f`; the check below prints `hospital_app 0` (no tenant, no
   rows); then sign in to the portal and open a patient.

   ```sh
   docker compose exec -T api python - <<'PY'
   from sqlalchemy import text
   from app.db import session_scope
   with session_scope() as s:
       print(s.scalar(text("select current_user")), s.scalar(text("select count(*) from patients")))
   PY
   ```

**Copy test** (before step 3): copy production into a throwaway
PostgreSQL 17 on a workstation and migrate it with this branch (from
`backend-hospital/`; `server` is the production host):

```sh
docker run -d --name hospital-copy -e POSTGRES_USER=hospital -e POSTGRES_PASSWORD=copy -e POSTGRES_DB=hospital -p 55433:5432 postgres:17-alpine
ssh server 'cd /opt/endod-hospital/deploy && docker compose exec -T postgres pg_dump -U hospital hospital' \
  | docker exec -i hospital-copy psql -q -U hospital -d hospital
HOSPITAL_ENVIRONMENT=development HOSPITAL_DATABASE_URL=postgresql+psycopg://hospital:copy@localhost:55433/hospital \
  HOSPITAL_APP_DB_PASSWORD=copy-app alembic upgrade head
HOSPITAL_ENVIRONMENT=development HOSPITAL_DATABASE_URL=postgresql+psycopg://hospital_app:copy-app@localhost:55433/hospital \
  uvicorn app.main:app --port 8100     # sign in as a real admin: their patients only
docker rm -f hospital-copy
```

### Rolling back

Nothing is lost either way; the policies only filter.

- **Switch the policies off, keep the code** (fastest; one statement per
  table): as `hospital`, `ALTER TABLE <table> DISABLE ROW LEVEL SECURITY;`
  for each of the 22 tables above (the same-hospital keys can stay), e.g.
  `docker compose exec -T postgres psql -U hospital -d hospital -c "select format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY;', relname) from pg_class where relrowsecurity" -At | docker compose exec -T postgres psql -U hospital -d hospital`.
  The app keeps working (as `hospital_app`, it then sees what it asks for).
  `ENABLE ROW LEVEL SECURITY` turns them back on.
- **Undo the migration**: `docker compose run --rm migrate alembic downgrade 0006`
  (drops the policies, functions and same-hospital keys), then deploy the
  previous commit, whose API connects as `hospital` again
  (`up -d --build --remove-orphans`).
  The roles can stay, or for each of `hospital_app` and `hospital_platform`:
  `DROP OWNED BY <role>; DROP ROLE <role>;`.

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
- **Isolation:** every query is scoped to the signed-in staff member's hospital,
  and on PostgreSQL row-level security enforces it again in the database
  (below).
- **Errors** look like `{"error": "...", "error_code": "..."}`.

Next: appointments, pharmacy, billing, reports, and the
link to the Endod patient platform.
