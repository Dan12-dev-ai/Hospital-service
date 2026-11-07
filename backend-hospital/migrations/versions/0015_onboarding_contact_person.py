"""Onboarding: a contact person other than the applicant

The application wizard asks each fact once: the account step creates the
login (name, email, password), and the contact person step defaults to that
person ("The contact person is me"), asking only their role and mobile. A
hospital may name someone else instead; this revision adds where that
person's name, mobile and email are kept, on ``onboarding_applications``.

All three are NULL for every application made before (the applicant was the
contact person, as it still is by default), so drafts resume unchanged. The
table keeps its row-level security; new columns need no new policy.

Downgrading drops the columns (applications that named someone else fall back
to the applicant as the contact person).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-07 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('onboarding_applications', sa.Column('contact_name', sa.String(length=120), nullable=True))
    op.add_column('onboarding_applications', sa.Column('contact_phone', sa.String(length=32), nullable=True))
    op.add_column('onboarding_applications', sa.Column('contact_email', sa.String(length=254), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('onboarding_applications') as batch:
        batch.drop_column('contact_email')
        batch.drop_column('contact_phone')
        batch.drop_column('contact_name')
