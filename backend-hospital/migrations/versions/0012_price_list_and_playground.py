"""the price list hospitals sync from their own system; the dashboard's playground connection

Endod becomes an integration layer: hospitals keep their own system, and the
staff portal becomes a developer dashboard. This revision adds:

* ``price_items``: each hospital's lab tests, imaging and procedures with
  their prices (santim), one row per code and category, replaced category by
  category by the integration API (``PUT /prices/...``). Row-level security
  like every hospital table (PostgreSQL: ENABLE, FORCE, ``tenant_isolation``,
  ``platform_access``; frozen copies of app/rls.py, which tests/test_rls.py
  checks). It refers to no other hospital row, so no composite key.
* ``integration_clients.playground``: the dashboard's own Test connection
  for its API playground (one per hospital, never listed or changed by
  staff). Every existing connection is not one (the server default). Only a
  column: the table's policies cover whole rows and are unchanged.

Downgrading drops both (the playground connections become ordinary Test
connections first, so none is left hidden: they are disconnected).

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-03 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None

PLATFORM_ROLE = "hospital_platform"
TENANT_TABLES = [("price_items", "hospital_id")]
TENANT_POLICY = "tenant_isolation"
PLATFORM_POLICY = "platform_access"
TENANT = "current_setting('app.hospital_id', true)"


def install_statements():
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


def _as_platform(bind, statement):
    """Run ``statement`` seeing every hospital's rows: as hospital_platform on
    PostgreSQL unless the login bypasses row-level security already."""
    switched = False
    if bind.dialect.name == "postgresql":
        bypass = bind.execute(sa.text("SELECT rolsuper OR rolbypassrls FROM pg_roles "
                                      "WHERE rolname = current_user")).scalar()
        if not bypass:
            if not bind.execute(sa.text("SELECT pg_has_role(current_user, :r, 'SET')"),
                                {"r": PLATFORM_ROLE}).scalar():
                raise RuntimeError(f"Cannot reach every hospital's connections: {PLATFORM_ROLE} is not available "
                                   "to this login. Run the migration as the database owner.")
            bind.execute(sa.text(f"SET LOCAL ROLE {PLATFORM_ROLE}"))
            switched = True
    try:
        bind.execute(sa.text(statement))
    finally:
        if switched:
            bind.execute(sa.text("RESET ROLE"))


def upgrade() -> None:
    op.add_column('integration_clients', sa.Column('playground', sa.Boolean(), nullable=False,
                                                   server_default=sa.text("false")))
    op.create_table('price_items',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('hospital_id', sa.String(length=32), nullable=False),
    sa.Column('category', sa.String(length=16), nullable=False),
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('price', sa.Integer(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'],
                            name=op.f('fk_price_items_hospital_id_hospitals'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_price_items')),
    sa.UniqueConstraint('hospital_id', 'category', 'code', name='uq_price_item_code')
    )
    op.create_index(op.f('ix_price_items_hospital_id'), 'price_items', ['hospital_id'], unique=False)
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in install_statements():
        op.execute(statement)


def downgrade() -> None:
    bind = op.get_bind()
    # No connection stays hidden once the dashboard that hides it is gone.
    _as_platform(bind, "UPDATE integration_clients SET revoked_at = CURRENT_TIMESTAMP, secret_hash = NULL "
                       "WHERE playground AND revoked_at IS NULL")
    if bind.dialect.name == "postgresql":
        for statement in drop_statements():
            op.execute(statement)
    op.drop_index(op.f('ix_price_items_hospital_id'), table_name='price_items')
    op.drop_table('price_items')
    with op.batch_alter_table('integration_clients') as batch:
        batch.drop_column('playground')
