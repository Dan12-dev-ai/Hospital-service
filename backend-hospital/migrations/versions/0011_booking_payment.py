"""bookings: how the patient pays (online to Endod, or at the hospital)

The patient platform's ``appointment.requested`` carries ``payment``:
``online`` (paid to Endod when booking, as every booking so far) or
``at_hospital`` (the patient pays the hospital at the visit). Existing
bookings were all paid online, which the server default records.

Only a column is added: the table's row-level security policies cover whole
rows and are unchanged.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-01 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bookings', sa.Column('payment', sa.String(length=12), nullable=False,
                                        server_default=sa.text("'online'")))


def downgrade() -> None:
    # A batch on SQLite rebuilds the table (dropping a column).
    with op.batch_alter_table('bookings') as batch:
        batch.drop_column('payment')
