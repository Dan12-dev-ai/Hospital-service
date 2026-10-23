"""prescription dispenses: medicine given at pharmacies through Endod

One new table, ``prescription_dispenses`` (docs/pharmacy.md, section 4), and
one new column, ``clinical_records.previous_dedan_id`` (the account a record
was last taken off). ADD COLUMN only, no batch: on SQLite no table that
others reference (``hospitals``, ``clinical_records``) is ever rebuilt.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-23 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('clinical_records', sa.Column('previous_dedan_id', sa.String(length=16), nullable=True))
    op.create_table('prescription_dispenses',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('hospital_id', sa.String(length=32), nullable=False),
    sa.Column('record_id', sa.String(length=32), nullable=False),
    sa.Column('dedan_id', sa.String(length=16), nullable=False),
    sa.Column('pharmacy_name', sa.String(length=120), nullable=False),
    sa.Column('dispensed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('items', sa.Text(), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'],
                            name=op.f('fk_prescription_dispenses_hospital_id_hospitals'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['record_id'], ['clinical_records.id'],
                            name=op.f('fk_prescription_dispenses_record_id_clinical_records'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prescription_dispenses'))
    )
    op.create_index('ix_prescription_dispenses_record', 'prescription_dispenses', ['record_id', 'dispensed_at'],
                    unique=False)


def downgrade() -> None:
    op.drop_index('ix_prescription_dispenses_record', table_name='prescription_dispenses')
    op.drop_table('prescription_dispenses')
    op.drop_column('clinical_records', 'previous_dedan_id')  # in place, as in 0005
