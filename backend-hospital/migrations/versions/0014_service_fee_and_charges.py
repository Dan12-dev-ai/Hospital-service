"""Endod's service fee and charges

The patient pays Endod a service fee on every payment for a hospital service
(docs/integrations.md "Charges"; the platform's docs/service-fee.md). This
revision adds:

* ``endod_fee_settings``: the fee settings the patient platform last sent
  (``fees.updated``; one row, belonging to no hospital: no row-level
  security, the app role may only read it, app/rls.py);
* ``charges``: bills for hospital services made through the integration API,
  with the fee applied (row-level security like every hospital table:
  ENABLE, FORCE, ``tenant_isolation``, ``platform_access``, and composite
  keys to its patient and booking; frozen copies of app/rls.py, which
  tests/test_rls.py checks);
* on ``bookings``: ``service_fee`` (0 for bookings made before), and when
  and how a visit paid at the hospital was paid.

Downgrading drops the tables and the columns (the platform keeps its fee
ledger).

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-03 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None

PLATFORM_ROLE = "hospital_platform"
TENANT_TABLES = [("charges", "hospital_id")]
SAME_HOSPITAL_REFERENCES = [("charges", "patient_id", "patients", "CASCADE"),
                            ("charges", "booking_id", "bookings", "SET NULL")]
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
    op.create_table('endod_fee_settings',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('flat_santim', sa.Integer(), nullable=False),
    sa.Column('percent_bp', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_endod_fee_settings'))
    )
    op.create_table('charges',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('hospital_id', sa.String(length=32), nullable=False),
    sa.Column('patient_id', sa.String(length=32), nullable=False),
    sa.Column('booking_id', sa.String(length=32), nullable=True),
    sa.Column('items', sa.String(length=60000).with_variant(sa.Text(), 'postgresql'), nullable=False),
    sa.Column('subtotal', sa.Integer(), nullable=False),
    sa.Column('service_fee', sa.Integer(), nullable=False),
    sa.Column('total', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('fee_version', sa.Integer(), nullable=False),
    sa.Column('fee_flat_santim', sa.Integer(), nullable=False),
    sa.Column('fee_percent_bp', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=8), nullable=False),
    sa.Column('method', sa.String(length=16), nullable=True),
    sa.Column('reference', sa.String(length=100), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('void_reason', sa.String(length=300).with_variant(sa.Text(), 'postgresql'), nullable=True),
    sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('client_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'],
                            name=op.f('fk_charges_booking_id_bookings'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'],
                            name=op.f('fk_charges_hospital_id_hospitals'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'],
                            name=op.f('fk_charges_patient_id_patients'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_charges'))
    )
    op.create_index('ix_charges_hospital_created', 'charges', ['hospital_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_charges_patient_id'), 'charges', ['patient_id'], unique=False)
    op.add_column('bookings', sa.Column('service_fee', sa.Integer(), server_default=sa.text('0'), nullable=False))
    op.add_column('bookings', sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('bookings', sa.Column('paid_method', sa.String(length=16), nullable=True))
    op.add_column('bookings', sa.Column('paid_reference', sa.String(length=100), nullable=True))
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in install_statements():
        op.execute(statement)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for statement in drop_statements():
            op.execute(statement)
    # A batch on SQLite rebuilds the table (dropping a column).
    with op.batch_alter_table('bookings') as batch:
        batch.drop_column('paid_reference')
        batch.drop_column('paid_method')
        batch.drop_column('paid_at')
        batch.drop_column('service_fee')
    op.drop_index(op.f('ix_charges_patient_id'), table_name='charges')
    op.drop_index('ix_charges_hospital_created', table_name='charges')
    op.drop_table('charges')
    op.drop_table('endod_fee_settings')
