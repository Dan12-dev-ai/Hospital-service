"""hospital onboarding: applications, documents, demo bookings

Adds ``hospitals.facility_type`` (hospital or clinic) with a plain
``ALTER TABLE ... ADD COLUMN``, never a batch: on SQLite a batch rebuilds
``hospitals``, and dropping the old table cascades to every row that
references it (patients and all). The rest are new tables.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-21 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('hospitals', sa.Column('facility_type', sa.String(length=8),
                                         server_default=sa.text("'hospital'"), nullable=False))

    op.create_table('onboarding_applications',
    sa.Column('hospital_id', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('contact_title', sa.String(length=80), nullable=True),
    sa.Column('license_number', sa.String(length=60), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejection_reason', sa.String(length=1000), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'],
                            name=op.f('fk_onboarding_applications_hospital_id_hospitals'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('hospital_id', name=op.f('pk_onboarding_applications'))
    )
    op.create_table('onboarding_documents',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('hospital_id', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('filename', sa.String(length=160), nullable=False),
    sa.Column('content_type', sa.String(length=40), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('uploaded_by', sa.String(length=32), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'],
                            name=op.f('fk_onboarding_documents_hospital_id_hospitals'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['staff_users.id'],
                            name=op.f('fk_onboarding_documents_uploaded_by_staff_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_onboarding_documents')),
    sa.UniqueConstraint('hospital_id', 'kind', name='uq_onboarding_document_kind')
    )
    op.create_table('demo_bookings',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('hospital_id', sa.String(length=32), nullable=False),
    sa.Column('slot_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'],
                            name=op.f('fk_demo_bookings_hospital_id_hospitals'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_demo_bookings')),
    sa.UniqueConstraint('hospital_id', name=op.f('uq_demo_bookings_hospital_id')),
    sa.UniqueConstraint('slot_start', name=op.f('uq_demo_bookings_slot_start'))
    )


def downgrade() -> None:
    op.drop_table('demo_bookings')
    op.drop_table('onboarding_documents')
    op.drop_table('onboarding_applications')
    op.drop_column('hospitals', 'facility_type')  # in place, as above
