"""encryption at rest: each hospital's data keys, and room for ciphertext

app/crypto.py explains the design. This revision:

* creates ``encryption_state`` (one row: whether plaintext is refused, set
  by ``python -m app.cli enforce-encryption``; it starts not enforced);
* creates ``hospital_keys`` (each hospital's data keys, wrapped under the
  master key, by version), with row-level security like every hospital
  table (PostgreSQL: ENABLE, FORCE, ``tenant_isolation`` and
  ``platform_access``; frozen copies of app/rls.py, which tests/test_rls.py
  checks);
* on PostgreSQL, makes the encrypted columns that were VARCHAR(n) TEXT
  (ciphertext is longer than the text; the API still limits the text).
  SQLite never enforces a VARCHAR's length, so nothing is rebuilt there.

No data is encrypted here: the ``migrate`` service has no master key (only
the API and worker do). After deploying, run ``python -m app.cli
encrypt-existing`` in the api container (README, "Encryption at rest").

Downgrading needs every value in plain text again (``python -m app.cli
decrypt-existing`` with THIS code, before ``alembic downgrade 0007``): it
refuses while any encrypted value is left, and then drops the keys.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-28 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

PLATFORM_ROLE = "hospital_platform"
TENANT_TABLES = [("hospital_keys", "hospital_id")]
TENANT_POLICY = "tenant_isolation"
PLATFORM_POLICY = "platform_access"
TENANT = "current_setting('app.hospital_id', true)"

#: Encrypted columns that were VARCHAR(n): (table, column, n).
WIDENED = [
    ("clinical_records", "title", 200),
    ("visits", "follow_up_note", 500),
    ("patients", "diagnosis", 200),
    ("patient_alerts", "label", 120),
    ("record_files", "filename", 160),
    ("shared_records", "title", 200),
]
#: Every encrypted column (app/sealing.py SEALED at this revision).
SEALED = {
    "clinical_records": ("title", "details"),
    "visits": ("follow_up_note",),
    "patients": ("diagnosis",),
    "patient_alerts": ("label",),
    "bookings": ("notes",),
    "record_files": ("filename",),
    "shared_records": ("title", "details", "files"),
    "import_batches": ("plan",),
}


def policy_statements():
    statements = []
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
    return statements


def upgrade() -> None:
    op.create_table('hospital_keys',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('hospital_id', sa.String(length=32), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('wrapped_key', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], name=op.f('fk_hospital_keys_hospital_id_hospitals'),
                            ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hospital_keys')),
    sa.UniqueConstraint('hospital_id', 'version', name='uq_hospital_keys_version')
    )
    op.create_index(op.f('ix_hospital_keys_hospital_id'), 'hospital_keys', ['hospital_id'], unique=False)
    op.create_table('encryption_state',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('enforced_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_encryption_state'))
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column, length in WIDENED:
        op.alter_column(table, column, type_=sa.Text(), existing_type=sa.String(length=length))
    for statement in policy_statements():
        op.execute(statement)


def downgrade() -> None:
    bind = op.get_bind()
    left = []
    for table, columns in SEALED.items():
        for column in columns:
            count = bind.execute(sa.text(f"SELECT count(*) FROM {table} WHERE {column} LIKE 'enc:v1:%'")).scalar()
            if count:
                left.append(f"{table}.{column}: {count}")
    if left:
        raise RuntimeError("Encrypted values are left; run `python -m app.cli decrypt-existing` with this code "
                           "first (README, 'Encryption at rest'): " + "; ".join(left))
    if bind.dialect.name == "postgresql":
        for statement in drop_statements():
            op.execute(statement)
        for table, column, length in WIDENED:
            op.alter_column(table, column, type_=sa.String(length=length), existing_type=sa.Text())
    op.drop_table('encryption_state')
    op.drop_index(op.f('ix_hospital_keys_hospital_id'), table_name='hospital_keys')
    op.drop_table('hospital_keys')
