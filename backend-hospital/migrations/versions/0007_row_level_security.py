"""row-level security: the database keeps hospitals apart (PostgreSQL)

app/rls.py explains the design. This revision adds, on PostgreSQL only:

* ``patient_alerts.hospital_id`` (every database), filled from the
  alert's patient, so an alert, its patient and its author share a hospital;
* the NOLOGIN role ``hospital_platform`` (if missing) for work done for
  Endod across hospitals (creating and altering roles, NOSUPERUSER and
  NOBYPASSRLS included, needs a superuser migration owner: POSTGRES_USER is
  one in the Compose deployment);
* composite foreign keys ``(hospital_id, x) -> parent (hospital_id, id)``
  (with UNIQUE (hospital_id, id) on the parents), so a row can only refer
  to rows of its own hospital. Existing rows are checked first: if any
  refers to another hospital's row, the migration fails, naming the table,
  column and row ids, and changes nothing;
* ENABLE and FORCE ROW LEVEL SECURITY on every table that belongs to a
  hospital, with ``tenant_isolation`` (the transaction's ``app.hospital_id``)
  and ``platform_access`` (role ``hospital_platform`` only);
* the SECURITY DEFINER lookups (sign-in, hospital codes, demo slots).

Apart from the new column, no data changes: a downgrade keeps every row.
The app role is created and granted by migrations/env.py (after this has
run).

Downgrading: stop the API and worker, run ``alembic downgrade 0006`` with
THIS code (the ``migrate`` service of this image: the 0006 image does not
know revision 0007 and cannot downgrade it), and only then deploy the 0006
code (README, "Rolling back").

The definitions are frozen copies of app/rls.py at this revision
(tests/test_rls.py checks they agree). On SQLite this does nothing.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-27 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

PLATFORM_ROLE = "hospital_platform"
TENANT_TABLES = [
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
]
CHILD_TABLES = {
    "staff_sessions": ("staff_users", "user_id"),
    "shared_records": ("record_shares", "share_id"),
}
SAME_HOSPITAL_REFERENCES = [
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
]
TENANT_POLICY = "tenant_isolation"
PLATFORM_POLICY = "platform_access"
TENANT = "current_setting('app.hospital_id', true)"
_DEFINER = "SECURITY DEFINER SET search_path = public, pg_temp"
FUNCTIONS = [
    ("hospital_of_staff_email(p_email text)",
     f"""RETURNS text LANGUAGE sql STABLE {_DEFINER} AS $$
        SELECT hospital_id::text FROM staff_users WHERE email = p_email $$"""),
    ("hospital_of_session_token(p_token_hash text)",
     f"""RETURNS text LANGUAGE sql STABLE {_DEFINER} AS $$
        SELECT u.hospital_id::text FROM staff_sessions s JOIN staff_users u ON u.id = s.user_id
        WHERE s.token_hash = p_token_hash AND s.revoked_at IS NULL AND s.expires_at > now() AND u.active $$"""),
    ("hospital_code_taken(p_code text)",
     f"""RETURNS boolean LANGUAGE sql STABLE {_DEFINER} AS $$
        SELECT EXISTS (SELECT 1 FROM hospitals WHERE code = p_code) $$"""),
    ("demo_slots_taken(p_hospital text, p_since timestamptz)",
     f"""RETURNS SETOF timestamptz LANGUAGE sql STABLE {_DEFINER} AS $$
        SELECT slot_start FROM demo_bookings
        WHERE slot_start >= p_since AND (p_hospital IS NULL OR hospital_id <> p_hospital) $$"""),
    ("demo_phone_taken(p_phone text, p_hospital text)",
     f"""RETURNS boolean LANGUAGE sql STABLE {_DEFINER} AS $$
        SELECT EXISTS (SELECT 1 FROM demo_bookings WHERE phone = p_phone AND hospital_id <> p_hospital) $$"""),
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
]


def _policy_tables():
    tables = [(t, f"({c} = {TENANT})") for t, c in TENANT_TABLES]
    tables += [(t, f"(EXISTS (SELECT 1 FROM {parent} p WHERE p.id = {t}.{fk}))")
               for t, (parent, fk) in CHILD_TABLES.items()]
    return tables


def _parents():
    return sorted({parent for _c, _col, parent, _d in SAME_HOSPITAL_REFERENCES})


def _fk(child, column):
    return f"fk_{child}_{column}_same_hospital"


def _unique(parent):
    return f"uq_{parent}_hospital_id_id"


def _function_names():
    names = []
    for signature, _body in FUNCTIONS:
        name, _, args = signature.partition("(")
        types = [part.strip().split()[-1] for part in args.rstrip(")").split(",") if part.strip()]
        names.append(f"{name}({', '.join(types)})")
    return names


def install_statements():
    statements = [f"""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PLATFORM_ROLE}') THEN
            CREATE ROLE {PLATFORM_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
        END IF;
    END $$""", f"ALTER ROLE {PLATFORM_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"]
    statements += [f"ALTER TABLE {child} DROP CONSTRAINT IF EXISTS {_fk(child, column)}"
                   for child, column, _p, _d in SAME_HOSPITAL_REFERENCES]
    for parent in _parents():
        statements += [f"ALTER TABLE {parent} DROP CONSTRAINT IF EXISTS {_unique(parent)}",
                       f"ALTER TABLE {parent} ADD CONSTRAINT {_unique(parent)} UNIQUE (hospital_id, id)"]
    for child, column, parent, on_delete in SAME_HOSPITAL_REFERENCES:
        action = "CASCADE" if on_delete == "CASCADE" else f"SET NULL ({column})"
        statements.append(
            f"ALTER TABLE {child} ADD CONSTRAINT {_fk(child, column)} FOREIGN KEY (hospital_id, {column}) "
            f"REFERENCES {parent} (hospital_id, id) ON DELETE {action}")
    for table, condition in _policy_tables():
        statements += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS {TENANT_POLICY} ON {table}",
            f"CREATE POLICY {TENANT_POLICY} ON {table} USING {condition} WITH CHECK {condition}",
            f"DROP POLICY IF EXISTS {PLATFORM_POLICY} ON {table}",
            f"CREATE POLICY {PLATFORM_POLICY} ON {table} TO {PLATFORM_ROLE} USING (true) WITH CHECK (true)",
        ]
    for (signature, body), name in zip(FUNCTIONS, _function_names()):
        statements += [f"CREATE OR REPLACE FUNCTION {signature} {body}",
                       f"ALTER FUNCTION {name} OWNER TO {PLATFORM_ROLE}",
                       f"REVOKE ALL ON FUNCTION {name} FROM PUBLIC"]
    return statements


def drop_statements():
    statements = [f"DROP FUNCTION IF EXISTS {name}" for name in _function_names()]
    for table, _condition in _policy_tables():
        statements += [
            f"DROP POLICY IF EXISTS {PLATFORM_POLICY} ON {table}",
            f"DROP POLICY IF EXISTS {TENANT_POLICY} ON {table}",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
        ]
    statements += [f"ALTER TABLE {child} DROP CONSTRAINT IF EXISTS {_fk(child, column)}"
                   for child, column, _p, _d in SAME_HOSPITAL_REFERENCES]
    statements += [f"ALTER TABLE {parent} DROP CONSTRAINT IF EXISTS {_unique(parent)}" for parent in _parents()]
    return statements


def cross_hospital_queries():
    queries = []
    for child, column, parent, _d in SAME_HOSPITAL_REFERENCES:
        key = "user_id" if child == "doctor_profiles" else "id"
        queries.append((child, column, f"SELECT c.{key} FROM {child} c JOIN {parent} p ON p.id = c.{column} "
                                       f"WHERE p.hospital_id <> c.hospital_id ORDER BY c.{key} LIMIT 20"))
    return queries


def _check_same_hospital(bind):
    problems = []
    for child, column, query in cross_hospital_queries():
        ids = [row[0] for row in bind.execute(sa.text(query))]
        if ids:
            problems.append(f"{child}.{column}: {', '.join(ids)}")
    if problems:
        raise RuntimeError("Rows refer to another hospital's rows; fix them before this migration: "
                           + "; ".join(problems))


def upgrade() -> None:
    # patient_alerts gets its patient's hospital (every database).
    op.add_column('patient_alerts', sa.Column('hospital_id', sa.String(length=32), nullable=True))
    op.execute("UPDATE patient_alerts SET hospital_id = "
               "(SELECT p.hospital_id FROM patients p WHERE p.id = patient_alerts.patient_id)")
    # A batch on SQLite rebuilds patient_alerts, which no table references.
    with op.batch_alter_table('patient_alerts') as batch:
        batch.alter_column('hospital_id', existing_type=sa.String(length=32), nullable=False)
        batch.create_foreign_key(op.f('fk_patient_alerts_hospital_id_hospitals'), 'hospitals',
                                 ['hospital_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_patient_alerts_hospital_id'), 'patient_alerts', ['hospital_id'], unique=False)
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    _check_same_hospital(bind)
    for statement in install_statements():
        op.execute(statement)


def downgrade() -> None:
    # Run with THIS revision's code, after stopping the API and worker, and
    # only then start the 0006 code (README, "Rolling back"): the 0006 image
    # cannot downgrade (it does not know 0007), and the 0007 code cannot run
    # without the functions this removes.
    # The hospital_platform role stays (a cluster object; harmless without the
    # policies). Remove it by hand if wanted: DROP OWNED BY hospital_platform;
    # DROP ROLE hospital_platform;
    if op.get_bind().dialect.name == "postgresql":
        for statement in drop_statements():
            op.execute(statement)
    op.drop_index(op.f('ix_patient_alerts_hospital_id'), table_name='patient_alerts')
    with op.batch_alter_table('patient_alerts') as batch:
        batch.drop_constraint(op.f('fk_patient_alerts_hospital_id_hospitals'), type_='foreignkey')
        batch.drop_column('hospital_id')
