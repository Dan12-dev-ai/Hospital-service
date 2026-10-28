"""Row-level security: the database's own wall between hospitals (PostgreSQL).

Every query in the API is already filtered by the signed-in staff member's
hospital. These policies are the second wall: even a query that forgets the
filter sees, and may write, only the rows of the hospital set for its
transaction (``app.hospital_id``, set by app.db.session_scope). With no
hospital set, a query sees nothing and every write is refused.

Roles (created and granted by migration 0007 and migrations/env.py):

* ``hospital`` owns the tables and runs the migrations (a superuser in the
  Compose deployment).
* ``hospital_app``: what the API and worker log in as. Not a superuser, no
  BYPASSRLS, owns nothing, no DDL; ``audit_events`` is SELECT and INSERT
  only, and ``outbox_events`` INSERT only (the worker reads it as the
  platform role).
* ``hospital_platform``: NOLOGIN, for work done for Endod across hospitals
  (``/platform`` routes, events from the bus, the worker's chores, the CLI).
  ``hospital_app`` is a member WITHOUT INHERIT: it has none of its rights
  until a transaction runs ``SET LOCAL ROLE hospital_platform``, which only
  app.db.platform_session does. Only this role has the ``platform_access``
  policy; no setting (GUC) opens anything.

Policies (ENABLE and FORCE on every table that belongs to a hospital):

* ``tenant_isolation`` on tables with ``hospital_id`` (and ``hospitals`` by
  ``id``): the row's hospital is ``current_setting('app.hospital_id')``.
* The two child tables without ``hospital_id`` (staff sessions, shared
  records) go through their parent row (``EXISTS`` on the
  parent, itself under its policy): a child is visible or writable exactly
  when its parent is, with no new column or backfill.
* ``platform_access`` (``hospital_platform`` only): every row.
* ``outbox_events`` and ``processed_events`` belong to no hospital (no
  policy; the outbox is kept from the app by its table rights).

Composite foreign keys ``(hospital_id, x) -> parent (hospital_id, id)`` sit
beside the plain ones: foreign keys ignore row security, so without them a
row could point at another hospital's patient, visit or staff member.

A few things must look past one hospital without a platform transaction:
signing in (the account's hospital is not known yet), a new hospital's code,
and other hospitals' demo bookings. Each is a SECURITY DEFINER function owned
by ``hospital_platform`` that returns only what is needed (a hospital id for
an account or a live session, a yes or no, slot times) or does one
fixed thing (release stale demo bookings).

Limits: this guards against mistakes in the app's own queries. SQL injected
into a query as ``hospital_app`` could still call ``set_config`` to choose
another hospital, or, with a second statement, ``SET ROLE hospital_platform``;
parameterised queries are what keep that out.

Migration 0007 installs these objects, 0008 the policies of
``hospital_keys`` (each hospital's wrapped data keys, app/crypto.py), and
0009 those of the integration API's tables and its client lookup; the
tests (which create the tables directly) call :func:`install`.
tests/test_rls.py checks they agree.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

APP_ROLE = "hospital_app"
PLATFORM_ROLE = "hospital_platform"

#: Tables with their own hospital column: (table, column).
TENANT_TABLES: List[Tuple[str, str]] = [
    ("hospitals", "id"),
    ("departments", "hospital_id"),
    ("staff_users", "hospital_id"),
    ("audit_events", "hospital_id"),
    ("doctor_profiles", "hospital_id"),
    ("patients", "hospital_id"),
    ("bookings", "hospital_id"),
    ("patient_link_requests", "hospital_id"),
    ("visits", "hospital_id"),
    ("clinical_records", "hospital_id"),
    ("record_files", "hospital_id"),
    ("queue_days", "hospital_id"),
    ("queue_entries", "hospital_id"),
    ("record_shares", "hospital_id"),
    ("import_batches", "hospital_id"),
    ("onboarding_applications", "hospital_id"),
    ("onboarding_documents", "hospital_id"),
    ("demo_bookings", "hospital_id"),
    ("prescription_dispenses", "hospital_id"),
    ("patient_alerts", "hospital_id"),
    # Migration 0008: the hospitals' wrapped data keys.
    ("hospital_keys", "hospital_id"),
    # Migration 0009: the integration API (app/integrations).
    ("integration_clients", "hospital_id"),
    ("integration_assertions", "hospital_id"),
    ("integration_requests", "hospital_id"),
    ("integration_resources", "hospital_id"),
    ("integration_idempotency", "hospital_id"),
    ("webhook_deliveries", "hospital_id"),
    # Migration 0010: two-step verification.
    ("staff_recovery_codes", "hospital_id"),
]

#: Child tables without a hospital column: table -> (parent, foreign key column).
CHILD_TABLES: Dict[str, Tuple[str, str]] = {
    "staff_sessions": ("staff_users", "user_id"),
    "shared_records": ("record_shares", "share_id"),
}

#: Tables that belong to no hospital.
SHARED_TABLES = ("outbox_events", "processed_events", "encryption_state")

#: Table rights other than full read and write, per role. The audit log is
#: append-only for both; the event outbox (patient names, phones, clinical
#: payloads of every hospital, with no hospital column) is write-only for the
#: app, which only emits events inside its transactions: reading, marking
#: sent and cleaning up are the worker's, as hospital_platform.
#: Data keys: the app only reads them and adds a hospital's first one; only
#: Endod (the CLI, as hospital_platform) activates a new version on rotation,
#: and nobody can change a wrapped key or delete one (without its key, a
#: hospital's data is lost).
#: encryption_state: whether encryption is enforced is set only by Endod; the
#: app may record which master key the database belongs to (first start, or
#: first data key), and the code only ever fills those columns while empty.
APP_RIGHTS = {"audit_events": "SELECT, INSERT", "outbox_events": "INSERT",
              "hospital_keys": "SELECT, INSERT",
              "encryption_state": "SELECT, INSERT, UPDATE (kek_check, kek_fingerprint, kek_recorded_at)"}
PLATFORM_RIGHTS = {"audit_events": "SELECT, INSERT", "hospital_keys": "SELECT, INSERT, UPDATE (active)",
                   "encryption_state": "SELECT, INSERT, UPDATE"}
APPEND_ONLY = ("audit_events",)

#: References between two rows of one hospital: (child, column, parent, on delete).
SAME_HOSPITAL_REFERENCES: List[Tuple[str, str, str, str]] = [
    ("staff_users", "department_id", "departments", "SET NULL"),
    ("audit_events", "actor_id", "staff_users", "SET NULL"),
    ("doctor_profiles", "user_id", "staff_users", "CASCADE"),
    ("patients", "department_id", "departments", "SET NULL"),
    ("patients", "ward_id", "departments", "SET NULL"),
    ("patients", "attending_doctor_id", "staff_users", "SET NULL"),
    ("patients", "created_by", "staff_users", "SET NULL"),
    ("bookings", "doctor_id", "staff_users", "SET NULL"),
    ("bookings", "decided_by", "staff_users", "SET NULL"),
    ("patient_link_requests", "patient_id", "patients", "CASCADE"),
    ("patient_link_requests", "requested_by", "staff_users", "SET NULL"),
    ("visits", "patient_id", "patients", "CASCADE"),
    ("visits", "doctor_id", "staff_users", "SET NULL"),
    ("visits", "booking_id", "bookings", "SET NULL"),
    ("visits", "created_by", "staff_users", "SET NULL"),
    ("clinical_records", "patient_id", "patients", "CASCADE"),
    ("clinical_records", "visit_id", "visits", "SET NULL"),
    ("clinical_records", "recorded_by", "staff_users", "SET NULL"),
    ("record_files", "patient_id", "patients", "CASCADE"),
    ("record_files", "record_id", "clinical_records", "CASCADE"),
    ("record_files", "uploaded_by", "staff_users", "SET NULL"),
    ("queue_days", "doctor_id", "staff_users", "CASCADE"),
    ("queue_entries", "queue_id", "queue_days", "CASCADE"),
    ("queue_entries", "patient_id", "patients", "SET NULL"),
    ("queue_entries", "booking_id", "bookings", "SET NULL"),
    ("queue_entries", "checked_in_by", "staff_users", "SET NULL"),
    ("import_batches", "created_by", "staff_users", "SET NULL"),
    ("onboarding_documents", "uploaded_by", "staff_users", "SET NULL"),
    ("prescription_dispenses", "record_id", "clinical_records", "CASCADE"),
    ("patient_alerts", "patient_id", "patients", "CASCADE"),
    ("patient_alerts", "created_by", "staff_users", "SET NULL"),
    # Migration 0009: the integration API.
    ("integration_clients", "created_by", "staff_users", "SET NULL"),
    ("integration_assertions", "client_pk", "integration_clients", "CASCADE"),
    ("integration_requests", "client_pk", "integration_clients", "CASCADE"),
    ("integration_resources", "client_pk", "integration_clients", "CASCADE"),
    ("integration_resources", "record_id", "clinical_records", "CASCADE"),
    ("integration_idempotency", "client_pk", "integration_clients", "CASCADE"),
    ("webhook_deliveries", "client_pk", "integration_clients", "CASCADE"),
    # Migration 0010: two-step verification.
    ("staff_recovery_codes", "user_id", "staff_users", "CASCADE"),
]

TENANT_POLICY = "tenant_isolation"
PLATFORM_POLICY = "platform_access"
TENANT = "current_setting('app.hospital_id', true)"


def tenant_condition(column: str) -> str:
    return f"({column} = {TENANT})"


def child_condition(table: str, parent: str, fk: str) -> str:
    return f"(EXISTS (SELECT 1 FROM {parent} p WHERE p.id = {table}.{fk}))"


def _policy_tables() -> List[Tuple[str, str]]:
    conditions = [(t, tenant_condition(c)) for t, c in TENANT_TABLES]
    conditions += [(t, child_condition(t, parent, fk)) for t, (parent, fk) in CHILD_TABLES.items()]
    return conditions


def parents() -> List[str]:
    return sorted({parent for _c, _col, parent, _d in SAME_HOSPITAL_REFERENCES})


def unique_name(parent: str) -> str:
    return f"uq_{parent}_hospital_id_id"


def fk_name(child: str, column: str) -> str:
    return f"fk_{child}_{column}_same_hospital"


def role_statements() -> List[str]:
    return [f"""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PLATFORM_ROLE}') THEN
            CREATE ROLE {PLATFORM_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
        END IF;
    END $$""", f"ALTER ROLE {PLATFORM_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"]


def policy_statements() -> List[str]:
    """Enable, force and (re)create the policies on every protected table."""
    statements: List[str] = []
    for table, condition in _policy_tables():
        statements += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS {TENANT_POLICY} ON {table}",
            f"CREATE POLICY {TENANT_POLICY} ON {table} USING {condition} WITH CHECK {condition}",
            f"DROP POLICY IF EXISTS {PLATFORM_POLICY} ON {table}",
            f"CREATE POLICY {PLATFORM_POLICY} ON {table} TO {PLATFORM_ROLE} USING (true) WITH CHECK (true)",
        ]
    return statements


def foreign_key_statements() -> List[str]:
    """The composite foreign keys (and the parents' unique keys they need)."""
    statements = [f"ALTER TABLE {child} DROP CONSTRAINT IF EXISTS {fk_name(child, column)}"
                  for child, column, _p, _d in SAME_HOSPITAL_REFERENCES]
    for parent in parents():
        statements += [f"ALTER TABLE {parent} DROP CONSTRAINT IF EXISTS {unique_name(parent)}",
                       f"ALTER TABLE {parent} ADD CONSTRAINT {unique_name(parent)} UNIQUE (hospital_id, id)"]
    for child, column, parent, on_delete in SAME_HOSPITAL_REFERENCES:
        action = "CASCADE" if on_delete == "CASCADE" else f"SET NULL ({column})"
        statements.append(
            f"ALTER TABLE {child} ADD CONSTRAINT {fk_name(child, column)} FOREIGN KEY (hospital_id, {column}) "
            f"REFERENCES {parent} (hospital_id, id) ON DELETE {action}")
    return statements


_DEFINER = "SECURITY DEFINER SET search_path = public, pg_temp"

#: (signature, body) of each SECURITY DEFINER function.
FUNCTIONS: List[Tuple[str, str]] = [
    # Sign-in: the hospital of the account with this exact email (also a
    # deactivated one, so its failed attempts count toward the lockout).
    ("hospital_of_staff_email(p_email text)",
     f"""RETURNS text LANGUAGE sql STABLE {_DEFINER} AS $$
        SELECT hospital_id::text FROM staff_users WHERE email = p_email $$"""),
    # Every request: the hospital of a live session (not revoked, not expired, active account).
    ("hospital_of_session_token(p_token_hash text)",
     f"""RETURNS text LANGUAGE sql STABLE {_DEFINER} AS $$
        SELECT u.hospital_id::text FROM staff_sessions s JOIN staff_users u ON u.id = s.user_id
        WHERE s.token_hash = p_token_hash AND s.revoked_at IS NULL AND s.expires_at > now() AND u.active $$"""),
    # Sign-up: codes are unique across hospitals.
    ("hospital_code_taken(p_code text)",
     f"""RETURNS boolean LANGUAGE sql STABLE {_DEFINER} AS $$
        SELECT EXISTS (SELECT 1 FROM hospitals WHERE code = p_code) $$"""),
    # Demo booking: slot times other hospitals hold (only the times).
    ("demo_slots_taken(p_hospital text, p_since timestamptz)",
     f"""RETURNS SETOF timestamptz LANGUAGE sql STABLE {_DEFINER} AS $$
        SELECT slot_start FROM demo_bookings
        WHERE slot_start >= p_since AND (p_hospital IS NULL OR hospital_id <> p_hospital) $$"""),
    # Demo booking: whether another hospital's demo holds this mobile.
    ("demo_phone_taken(p_phone text, p_hospital text)",
     f"""RETURNS boolean LANGUAGE sql STABLE {_DEFINER} AS $$
        SELECT EXISTS (SELECT 1 FROM demo_bookings WHERE phone = p_phone AND hospital_id <> p_hospital) $$"""),
    # Release demo bookings held for nothing (app.onboarding.release_stale).
    ("release_stale_demo_bookings(p_cutoff timestamptz)",
     f"""RETURNS integer LANGUAGE sql VOLATILE {_DEFINER} AS $$
        WITH gone AS (
            DELETE FROM demo_bookings d
            WHERE (d.created_at < p_cutoff AND d.hospital_id IN (
                       SELECT hospital_id FROM onboarding_applications WHERE status IN ('draft', 'rejected')))
               OR d.hospital_id IN (
                       SELECT h.id FROM hospitals h JOIN onboarding_applications a ON a.hospital_id = h.id
                       WHERE h.status = 'suspended' AND a.status <> 'approved')
            RETURNING 1)
        SELECT count(*)::integer FROM gone $$"""),
    # Migration 0009, the integration API's token endpoint: the hospital of a
    # client (a revoked one too: it is refused afterwards, with the same work).
    ("hospital_of_integration_client(p_client_id text)",
     f"""RETURNS text LANGUAGE sql STABLE {_DEFINER} AS $$
        SELECT hospital_id::text FROM integration_clients WHERE client_id = p_client_id $$"""),
]


def function_names() -> List[str]:
    """``name(type, ...)`` of each function, as GRANT and DROP take them."""
    names = []
    for signature, _body in FUNCTIONS:
        name, _, args = signature.partition("(")
        types = [part.strip().split()[-1] for part in args.rstrip(")").split(",") if part.strip()]
        names.append(f"{name}({', '.join(types)})")
    return names


def function_statements() -> List[str]:
    statements = []
    for (signature, body), name in zip(FUNCTIONS, function_names()):
        statements += [f"CREATE OR REPLACE FUNCTION {signature} {body}",
                       f"ALTER FUNCTION {name} OWNER TO {PLATFORM_ROLE}",
                       f"REVOKE ALL ON FUNCTION {name} FROM PUBLIC"]
    return statements


def install_statements() -> List[str]:
    return role_statements() + foreign_key_statements() + policy_statements() + function_statements()


def drop_statements() -> List[str]:
    """Undo everything but the role (a cluster object); the data stays."""
    statements = [f"DROP FUNCTION IF EXISTS {name}" for name in function_names()]
    for table, _condition in _policy_tables():
        statements += [
            f"DROP POLICY IF EXISTS {PLATFORM_POLICY} ON {table}",
            f"DROP POLICY IF EXISTS {TENANT_POLICY} ON {table}",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
        ]
    statements += [f"ALTER TABLE {child} DROP CONSTRAINT IF EXISTS {fk_name(child, column)}"
                   for child, column, _p, _d in SAME_HOSPITAL_REFERENCES]
    statements += [f"ALTER TABLE {parent} DROP CONSTRAINT IF EXISTS {unique_name(parent)}" for parent in parents()]
    return statements


def cross_hospital_queries() -> List[Tuple[str, str, str]]:
    """(child, column, query): the child rows that refer to another hospital's
    row, which the composite keys would refuse. Run before adding them."""
    queries = []
    for child, column, parent, _d in SAME_HOSPITAL_REFERENCES:
        key = "user_id" if child == "doctor_profiles" else "id"
        queries.append((child, column, f"SELECT c.{key} FROM {child} c JOIN {parent} p ON p.id = c.{column} "
                                       f"WHERE p.hospital_id <> c.hospital_id ORDER BY c.{key} LIMIT 20"))
    return queries


def check_same_hospital(connection) -> None:
    """Fail, naming table, column and row ids, if existing rows refer to
    another hospital's rows (the composite keys could not be added)."""
    problems = []
    for child, column, query in cross_hospital_queries():
        ids = [row[0] for row in connection.execute(text(query))]
        if ids:
            problems.append(f"{child}.{column}: {', '.join(ids)}")
    if problems:
        raise RuntimeError("Rows refer to another hospital's rows; fix them before this migration: "
                           + "; ".join(problems))


def install(connection) -> None:
    """Install the role, keys, policies and functions (PostgreSQL only; idempotent)."""
    if connection.dialect.name != "postgresql":
        return
    check_same_hospital(connection)
    for statement in install_statements():
        connection.execute(text(statement))


# --- the app role ---------------------------------------------------------------------------

_ROLE_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def checked_role(role: str) -> str:
    if not _ROLE_NAME.fullmatch(role or ""):
        raise RuntimeError("The app role must be a plain lower-case role name.")
    return role


def role_exists(connection, role: str) -> bool:
    return bool(connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar())


def scram_verifier(password: str) -> str:
    """The SCRAM-SHA-256 verifier PostgreSQL stores for ``password``.

    ``CREATE/ALTER ROLE ... PASSWORD`` is given this instead of the password,
    so the password itself never reaches the server (nor its statement log).
    PostgreSQL normalises non-ASCII passwords (SASLprep) before hashing; this
    does not, so the password must be ASCII (the deploy uses hex)."""
    if not password.isascii():
        raise RuntimeError("HOSPITAL_APP_DB_PASSWORD must be ASCII (e.g. openssl rand -hex 32).")
    iterations = 4096
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = lambda raw: base64.b64encode(raw).decode()  # noqa: E731
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def ensure_app_role(connection, role: str, password: Optional[str]) -> None:
    """Create the app role if it is missing (idempotent; also on an existing
    database), and keep its attributes as they must be: it logs in, and is
    never a superuser, never bypasses row security and creates nothing.
    Without a password, a missing role is not created and an existing one
    keeps its password."""
    role = checked_role(role)
    exists = role_exists(connection, role)
    if not exists and not password:
        return
    # Setting NOSUPERUSER and NOBYPASSRLS takes a superuser: the migration
    # owner is one in the Compose deployment (POSTGRES_USER).
    attributes = "LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION"
    if password:
        # Only the SCRAM verifier is sent, never the password (see scram_verifier).
        attributes += f" PASSWORD '{scram_verifier(password)}'"
    verb = "ALTER" if exists else "CREATE"
    # Straight to the driver without parameters (the verifier holds "$", "+", "/").
    cursor = connection.connection.cursor()
    try:
        cursor.execute(f'{verb} ROLE "{role}" {attributes}')
    finally:
        cursor.close()


def _grant_tables(connection, role: str, tables, rights: Dict[str, str]) -> None:
    for table in sorted(tables):
        if connection.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}).scalar() is None:
            continue  # not there (yet, or any more after a downgrade)
        connection.execute(text(f'REVOKE ALL ON TABLE "{table}" FROM "{role}"'))
        privileges = rights.get(table, "SELECT, INSERT, UPDATE, DELETE")
        connection.execute(text(f'GRANT {privileges} ON TABLE "{table}" TO "{role}"'))


def grant_app_role(connection, role: str, tables) -> None:
    """Exactly what the app needs: connect, use the schema, read and write the
    app tables (rows as the policies allow; the audit log only read and
    appended), read alembic_version, call the lookups, and enter the platform
    role (without inheriting it). The platform role gets the same table rights.
    Run after every upgrade (migrations/env.py)."""
    role = checked_role(role)
    if not role_exists(connection, role):
        return
    database = connection.execute(text("SELECT current_database()")).scalar()
    connection.execute(text(f'GRANT CONNECT ON DATABASE "{database}" TO "{role}"'))
    connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
    _grant_tables(connection, role, tables, APP_RIGHTS)
    if connection.execute(text("SELECT to_regclass('public.alembic_version')")).scalar() is not None:
        connection.execute(text(f'REVOKE ALL ON TABLE alembic_version FROM "{role}"'))
        connection.execute(text(f'GRANT SELECT ON TABLE alembic_version TO "{role}"'))
    if not role_exists(connection, PLATFORM_ROLE):
        return  # before migration 0007
    connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {PLATFORM_ROLE}"))
    _grant_tables(connection, PLATFORM_ROLE, tables, PLATFORM_RIGHTS)
    connection.execute(text(f'GRANT {PLATFORM_ROLE} TO "{role}" WITH INHERIT FALSE, SET TRUE'))
    for name in function_names():
        if connection.execute(text("SELECT to_regprocedure(:f)"), {"f": name}).scalar() is not None:
            connection.execute(text(f'GRANT EXECUTE ON FUNCTION {name} TO "{role}"'))


def set_up_app_role(connection, role: str, password: Optional[str], tables) -> None:
    """After the migrations (migrations/env.py): create or update the app
    role and grant it. Fails, never skips, when the role is missing."""
    role = checked_role(role)
    if connection.execute(text("SELECT current_user")).scalar() == role:
        raise RuntimeError(f"Run the migrations as the owner, not as the app role {role}.")
    ensure_app_role(connection, role, password)
    if not role_exists(connection, role):
        raise RuntimeError(f"The app role {role} does not exist: set HOSPITAL_APP_DB_PASSWORD and the "
                           "migration creates it (the API and worker connect as it).")
    grant_app_role(connection, role, tables)


def connection_role_problem(connection) -> Optional[str]:
    """Why the current login must not run the app (None: it may)."""
    superuser, bypass, owned = connection.execute(text(
        "SELECT r.rolsuper, r.rolbypassrls, (SELECT count(*) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relowner = r.oid) "
        "FROM pg_roles r WHERE r.rolname = current_user")).one()
    if superuser:
        return "is a superuser"
    if bypass:
        return "has BYPASSRLS"
    if owned:
        return "owns tables"
    return None


# --- lookups (SQLite, without policies, gets the same answers from plain queries) -----------

def _postgres(session: Session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def hospital_of_email(session: Session, email: str) -> Optional[str]:
    """The hospital of the staff account with this exact (stored) email, if any."""
    if _postgres(session):
        return session.scalar(text("SELECT hospital_of_staff_email(:email)"), {"email": email})
    return session.scalar(text("SELECT hospital_id FROM staff_users WHERE email = :email"),
                          {"email": email})


def hospital_of_token(session: Session, digest: str) -> Optional[str]:
    """The hospital of the live session with this token hash, if any."""
    if _postgres(session):
        return session.scalar(text("SELECT hospital_of_session_token(:digest)"), {"digest": digest})
    from sqlalchemy import select

    from app.db import ensure_aware, utcnow
    from app.models import StaffSession, StaffUser

    row = session.execute(select(StaffSession, StaffUser).join(StaffUser, StaffUser.id == StaffSession.user_id)
                          .where(StaffSession.token_hash == digest)).first()
    if row is None:
        return None
    sess, user = row
    if sess.revoked_at is not None or ensure_aware(sess.expires_at) <= utcnow() or not user.active:
        return None
    return user.hospital_id


def hospital_of_integration_client(session: Session, client_id: str) -> Optional[str]:
    """The hospital of the integration client with this (public) client_id, if any."""
    if _postgres(session):
        return session.scalar(text("SELECT hospital_of_integration_client(:c)"), {"c": client_id})
    return session.scalar(text("SELECT hospital_id FROM integration_clients WHERE client_id = :c"),
                          {"c": client_id})


def hospital_code_taken(session: Session, code: str) -> bool:
    if _postgres(session):
        return bool(session.scalar(text("SELECT hospital_code_taken(:code)"), {"code": code}))
    return session.scalar(text("SELECT 1 FROM hospitals WHERE code = :code"), {"code": code}) is not None
