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
  `hospital_app`: not a superuser, no BYPASSRLS, owns nothing, no DDL; the
  audit log is SELECT and INSERT only, and the event outbox (patient names,
  phones and clinical payloads of every hospital) INSERT only: the worker
  reads, marks and deletes it as `hospital_platform`. `hospital_platform` (NOLOGIN)
  acts for Endod across hospitals; `hospital_app` is a member without
  INHERIT, so it has none of its rights until a transaction runs
  `SET LOCAL ROLE hospital_platform`. `migrations/env.py` creates
  `hospital_app` when `HOSPITAL_APP_DB_PASSWORD` is set (or sets its password
  and attributes again) and grants it after every upgrade, on a new and an
  existing database alike; without the role the migration fails. Creating
  and altering roles (NOSUPERUSER, NOBYPASSRLS) needs a superuser migration
  owner, which `hospital` (POSTGRES_USER) is. The password is never sent to
  the server: only its SCRAM-SHA-256 verifier is (so it cannot reach the
  statement log); it must be ASCII (hex, as below).
- **Refusal at start.** The API and the worker refuse to start when their
  login is a superuser, has BYPASSRLS or owns the tables.
- **Tenant per transaction.** `session_scope(staff.hospital_id)` sets
  `app.hospital_id` for its transaction only (`set_config(..., true)`, i.e.
  `SET LOCAL`, in an `after_begin` hook, so it never reaches the next user of
  a pooled connection). Every staff route passes the signed-in staff
  member's hospital. Every checkout from the pool also runs `RESET ROLE;
  RESET ALL`, so even a session-level `SET ROLE` or setting cannot carry over
  to the next request.
- **Platform scope.** `platform_session()` is the only place that takes the
  `hospital_platform` role: `/platform/...` routes (X-Platform-Key), events
  from the bus (`eventbus._handle`), the worker's chores and expiries, and the
  CLI. No setting (GUC) opens anything: only that role has the
  `platform_access` policy.
- **Narrow lookups.** What must look past one hospital outside a platform
  transaction goes through SECURITY DEFINER functions owned by
  `hospital_platform`, with `search_path = public, pg_temp`, EXECUTE revoked
  from PUBLIC and granted to `hospital_app`, returning only what is needed:
  `hospital_of_staff_email` (sign-in; a deactivated account is found too, so
  that its attempts, answered with the same 401, count toward the lockout),
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
  `prescription_dispenses`, `patient_alerts` (its `hospital_id` is new in
  0007, filled from the alert's patient). The two tables without
  `hospital_id` (`staff_sessions`, `shared_records`) are covered through
  their parent (`EXISTS` on `staff_users`, `record_shares`, under their own
  policies): a child can never disagree with its parent. `outbox_events` and
  `processed_events` belong to no hospital (the outbox is kept from the app
  by its table rights).
- **Same-hospital references.** Foreign keys ignore row security, so 31
  composite keys `(hospital_id, x) -> parent (hospital_id, id)` (with
  `UNIQUE (hospital_id, id)` on the parents) make a record, file, visit,
  queue entry, dispense... refer only to rows of its own hospital, with the
  same ON DELETE as the plain key (`SET NULL (x)` keeps `hospital_id`).
  Before adding them the migration looks for existing rows that point at
  another hospital's and, if there are any, fails with their table, column
  and ids, changing nothing.
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

The migration adds `patient_alerts.hospital_id` (filled from each alert's patient), a role, keys, policies and functions; no other data changes.
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
- **Undo the migration.** Order matters: the 0006 image cannot downgrade
  (it does not know revision 0007; started on a database at 0007 its
  `alembic upgrade head` fails), and the 0007 code cannot run once the
  downgrade removed its functions. So stop the 0007 API and worker, downgrade
  with the 0007 image's `migrate` service, and only then start the 0006 code:

  ```sh
  cd /opt/endod-hospital/deploy
  docker compose --env-file .env stop api worker portal
  docker compose --env-file .env run --rm migrate alembic downgrade 0006
  cd .. && git checkout 06b5433          # the last commit before row-level security
  cd deploy && docker compose --env-file .env up -d --build --remove-orphans
  ```

  The downgrade drops the policies, functions, same-hospital keys and
  `patient_alerts.hospital_id`; every row stays. The 0006 API connects as
  `hospital` again. The roles can stay, or for each of `hospital_app` and
  `hospital_platform`: `DROP OWNED BY <role>; DROP ROLE <role>;`.

## Encryption at rest

Health data is encrypted by the app before it reaches the database or the
disk (`app/crypto.py`, `app/sealing.py`, migration 0008), so a copy of the
database, a backup or the files volume alone reveals no clinical data.

- **Envelope encryption.** A master key (KEK, 32 random bytes) lives in a
  file (`HOSPITAL_MASTER_KEY_FILE`), mounted read-only into the API and the
  worker only: never in the database, the repository, the `migrate` service
  or a log. Each hospital has its own data key (DEK, 32 bytes) in
  `hospital_keys`, wrapped with AES-256-GCM under the master key, by version
  (one active). `hospital_keys` is under row-level security like every
  hospital table. Unwrapped data keys are cached in memory for 5 minutes,
  by the wrapped key's digest (a key row rolled back with its savepoint is
  never served from the cache), and any failed decryption, of a value or a
  file, evicts the cached key and retries once.
  **Fails closed:** the API, the worker and the CLI refuse to start without a
  usable master key unless `HOSPITAL_ENVIRONMENT` is *explicitly* set to
  `development` or `test` (then a fixed, public development key is used:
  never for real data). At start they log the key's fingerprint
  (`master_key_loaded fingerprint=…`, a hash, not the key), so you can tell
  which key a server runs with.
- **Values** are stored as `enc:v1:<key version>:` + base64(nonce ‖
  ciphertext ‖ tag), AES-256-GCM with a random 12-byte nonce each time. The
  associated data names the table, column, row id, hospital and key version:
  a value copied to another row, column or hospital does not decrypt.
  Encryption happens on flush and decryption on load, so the code above the
  models is unchanged. If a flush fails, its objects get their plain text
  back and are encrypted again, with the key active then, on the next one.
- **Files** (record files, onboarding documents) are encrypted as they are
  uploaded, in 64 KiB chunks, each with a random nonce and associated data
  naming the hospital, file id, chunk index and whether it is the last (a
  file cut short or reordered does not decrypt). The stored size and sha256
  are the plain file's; every download is decrypted and checked against them
  before the first byte is sent. Files shared by patients are fetched from
  the platform on demand and held in memory only.
- **Enforcement.** Until `python -m app.cli enforce-encryption` (which
  refuses unless `check-encryption` is clean), a value or file stored before
  encryption is read as it is; that includes legacy text that merely starts
  with `enc:v1:` (only a well-formed value counts as encrypted, and
  `encrypt-existing` encrypts the rest). Once enforced, anything not
  encrypted is refused, and logged by table, column and row id (never the
  value).
- **The outbox.** Events to the platform carry clinical payloads in plain
  text (the platform needs them) until they are sent; a sent row is deleted
  after 24 hours (the worker's hourly housekeeping).
- **Redis.** Events are plain text in Redis while in flight: from when they
  are sent until every consumer group on the stream has acknowledged them.
  Then they are deleted: the worker deletes the events it produced every 10
  seconds, once every group on `endod:hospital` acknowledged them, and the
  events it received right after acknowledging them (once every group on
  `endod:patient` has). Events nobody reads are trimmed after 7 days. The
  dead-letter stream keeps only the event's id, type, source, time, the error
  (500 characters at most) and a redacted payload (field names, and the
  values of `*_id` fields; no clinical data, names or phones), about 10,000
  entries at most.

| Encrypted | Not encrypted, and why |
| --- | --- |
| Clinical records: `title` (it usually names the diagnosis: "Malaria", "HIV test") and `details` | Patients' names, Amharic names, phone numbers, MRNs and Endod IDs: staff search by them (`LIKE`), which ciphertext cannot serve |
| Visits' follow-up notes; the working diagnosis on the patient; allergy and risk alerts' text | Dates, categories, statuses, wards and beds: filtered and sorted in SQL; they say little on their own |
| Booking notes from the patient app (often symptoms) | A retraction's reason ("entered in error") and the audit log (ids, categories, never clinical text; alert labels are no longer written there) |
| Records patients shared: title, details and file list | Pharmacies' dispense amounts (item indexes and counts) |
| Record files' names and contents; onboarding documents' contents | Hospital, staff and onboarding details (not health data) |
| Import previews (the parsed records; the uploaded file itself is never stored) | Events in flight in Redis, until every reader acknowledged them (see above; the bus is private) |

### The master key

Generate it once, on the server, as root:

```sh
install -d -m 0700 -o root -g root /opt/endod-hospital/deploy/keys
openssl rand -out /opt/endod-hospital/deploy/keys/master.key 32
chown 10002:10002 /opt/endod-hospital/deploy/keys/master.key   # the image's `hospital` user
chmod 0400 /opt/endod-hospital/deploy/keys/master.key
```

Only root on the host can reach it (the `keys` directory is root's, 0700);
the file is owned by uid 10002, which has no account on the host, because
the containers run as that user and a root-owned 0400 file could not be read
in them. `deploy/docker-compose.yml` mounts it read-only at
`/run/secrets/master.key` into the API and the worker only (and refuses to
start if it is missing, rather than creating a directory there).

**Back it up OFFLINE now, together with the backup key** (e.g. printed
`base64 master.key` and a USB stick in the safe, never in the same place as
the backups). Losing the master key means losing every hospital's clinical
data and files, in the database and in every backup; a stolen master key
alone decrypts nothing without the database, and the database alone nothing
without the key. Never rotate it by replacing the file: the data keys are
wrapped under it.

### Deploying it

Production has 4 hospitals and no patients, so there is little to encrypt;
the steps are the same with data.

1. Create and back up the master key (above).
2. `cd /opt/endod-hospital && git pull` (this branch, once merged), then
   `cd deploy && docker compose --env-file .env up -d --build`. `migrate`
   runs 0008 (the `hospital_keys` table, with its policies; TEXT for the
   encrypted columns that were VARCHAR); the API and worker start with the key.
3. Check the logs show the key's fingerprint (`docker compose logs api worker
   | grep master_key_loaded`), and that it is the fingerprint of the key you
   backed up (`python -m app.cli check-encryption` prints it too).
4. Encrypt what was stored before (in batches; safe to stop and run again),
   check, then enforce:

   ```sh
   docker compose exec api python -m app.cli encrypt-existing
   docker compose exec api python -m app.cli check-encryption   # exit 0: nothing left in plain text
   docker compose exec api python -m app.cli enforce-encryption # from now on plaintext is refused
   ```

5. Sign in to the portal, open a patient's records and a file.

**Rotating a hospital's data key** (yearly, or if a key may have leaked):
`docker compose exec api python -m app.cli rotate-key --hospital SPH`. It adds
a new version, makes it active and re-encrypts that hospital's values and
files; the old version stays, inactive, so backups taken before stay
readable. Old versions are never purged, so nothing can be stranded: a file
whose upload started before the rotation is stored with the key active when
it started. `check-encryption` then counts it "on an older key", and
`rotate-key --hospital SPH --resume` moves such stragglers to the active
version without making another one.

An operator who needs a stored file (an onboarding document, say) gets it
decrypted with `python -m app.cli export-file --file <id> --out <path>`.

### Rolling back

This code reads plain and encrypted values alike, so it can stay while
anything is investigated. The 0007 code reads only plain text: to go back to
it, stop everything that writes, decrypt everything with THIS image, then
downgrade with THIS image's `migrate`, and only then deploy the old code.
The downgrade refuses while any encrypted value is left; it cannot see the
files, so never skip `decrypt-existing` (it does both, and lifts enforcement
first).

  ```sh
  cd /opt/endod-hospital/deploy
  docker compose --env-file .env stop portal worker api
  docker compose --env-file .env run --rm --no-deps api python -m app.cli decrypt-existing --yes
  docker compose --env-file .env run --rm migrate alembic downgrade 0007
  cd .. && git checkout ead871d          # the last commit before encryption at rest
  cd deploy && docker compose --env-file .env up -d --build --remove-orphans
  ```

  Keep the master key: backups taken while encryption was on need it.

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
