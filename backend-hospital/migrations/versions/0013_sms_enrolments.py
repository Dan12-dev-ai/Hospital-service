"""SMS enrolments: patients without an Endod account enrolled by an SMS code

A hospital enrols a patient who has no Endod account (often no smartphone):
Endod texts a code to the patient's phone, reception types it, and Endod
creates (or finds) the account and links the patient (app/linking.py,
docs/history-events.md section 8). This revision adds ``sms_enrolments``,
one row per request, with row-level security like every hospital table
(PostgreSQL: ENABLE, FORCE, ``tenant_isolation``, ``platform_access``, and a
composite key to its patient; frozen copies of app/rls.py, which
tests/test_rls.py checks).

Downgrading drops the table (the requests only; enrolled patients keep their
Endod ID).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-03 14:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None

PLATFORM_ROLE = "hospital_platform"
TENANT_TABLES = [("sms_enrolments", "hospital_id")]
SAME_HOSPITAL_REFERENCES = [("sms_enrolments", "patient_id", "patients", "CASCADE")]
TENANT_POLICY = "tenant_isolation"
PLATFORM_POLICY = "platform_access"
TENANT = "current_setting('app.hospital_id', true)"


def _fk(child, column):
    return f"fk_{child}_{column}_same_hospital"


def install_statements():
    statements = [f"ALTER TABLE {child} DROP CONSTRAINT IF EXISTS {_fk(child, column)}"
                  for child, column, _p, _d in SAME_HOSPITAL_REFERENCES]
    for child, column, parent, on_delete in SAME_HOSPITAL_REFERENCES:
        action = "CASCADE" if on_delete == "CASCADE" else f"SET NULL ({column})"
        statements.append(
            f"ALTER TABLE {child} ADD CONSTRAINT {_fk(child, column)} FOREIGN KEY (hospital_id, {column}) "
            f"REFERENCES {parent} (hospital_id, id) ON DELETE {action}")
    for table, column in TENANT_TABLES:
        condition = f"({column} = {TENANT})"
        statements += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS {TENANT_POLICY} ON {table}",
            f"CREATE POLICY {TENANT_POLICY} ON {table} USING {condition} WITH CHECK {condition}",
            f"DROP POLICY IF EXISTS {PLATFORM_POLICY} ON {table}",
            f"CREATE POLICY {PLATFORM_POLICY} ON {table} TO {PLATFORM_ROLE} USING (true) WITH CHECK (true)",
        ]
    return statements


def drop_statements():
    statements = []
    for table, _column in TENANT_TABLES:
        statements += [
            f"DROP POLICY IF EXISTS {PLATFORM_POLICY} ON {table}",
            f"DROP POLICY IF EXISTS {TENANT_POLICY} ON {table}",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
        ]
    statements += [f"ALTER TABLE {child} DROP CONSTRAINT IF EXISTS {_fk(child, column)}"
                   for child, column, _p, _d in SAME_HOSPITAL_REFERENCES]
    return statements


def upgrade() -> None:
    op.create_table('sms_enrolments',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('hospital_id', sa.String(length=32), nullable=False),
    sa.Column('patient_id', sa.String(length=32), nullable=False),
    sa.Column('phone', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('reason', sa.String(length=40), nullable=True),
    sa.Column('attempts_left', sa.Integer(), nullable=True),
    sa.Column('dedan_id', sa.String(length=16), nullable=True),
    sa.Column('created_account', sa.Boolean(), nullable=True),
    sa.Column('code_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'],
                            name=op.f('fk_sms_enrolments_hospital_id_hospitals'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'],
                            name=op.f('fk_sms_enrolments_patient_id_patients'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sms_enrolments'))
    )
    op.create_index('ix_sms_enrolments_patient', 'sms_enrolments', ['patient_id', 'created_at'], unique=False)
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in install_statements():
        op.execute(statement)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for statement in drop_statements():
            op.execute(statement)
    op.drop_index('ix_sms_enrolments_patient', table_name='sms_enrolments')
    op.drop_table('sms_enrolments')
