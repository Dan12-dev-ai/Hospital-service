"""two-step verification: authenticator secrets, session stages, recovery codes

Staff of hospitals approved by Endod sign in with their password and a code
from an authenticator app (app/twofactor.py). This revision only adds:

* ``staff_users``: the TOTP secret and one waiting for its first code (both
  encrypted at rest by the app), the last step used, when it was set up, and
  the account-wide pause after wrong codes;
* ``staff_sessions``: the stage of a sign-in (``full``, ``totp``, ``enroll``;
  every existing session is a ``full`` one) and when the session last gave a
  fresh code (re-authentication);
* ``staff_recovery_codes`` (keyed hashes of one-time codes), with row-level
  security like every hospital table (PostgreSQL: ENABLE, FORCE,
  ``tenant_isolation``, ``platform_access``, and a composite key to its staff
  member; frozen copies of app/rls.py, which tests/test_rls.py checks).

Nobody is signed out by the migration: approved hospitals' staff set up their
authenticator at their next sign-in. Downgrading drops what this added.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-29 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None

PLATFORM_ROLE = "hospital_platform"
TENANT_TABLES = [("staff_recovery_codes", "hospital_id")]
SAME_HOSPITAL_REFERENCES = [("staff_recovery_codes", "user_id", "staff_users", "CASCADE")]
TENANT_POLICY = "tenant_isolation"
PLATFORM_POLICY = "platform_access"
TENANT = "current_setting('app.hospital_id', true)"

USER_COLUMNS = [
    ("totp_secret", sa.Text(), None),
    ("totp_pending_secret", sa.Text(), None),
    ("totp_last_step", sa.Integer(), None),
    ("totp_enrolled_at", sa.DateTime(timezone=True), None),
    ("code_failures", sa.Integer(), sa.text("0")),
    ("code_last_failed_at", sa.DateTime(timezone=True), None),
    ("code_backoff_until", sa.DateTime(timezone=True), None),
]


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
    for name, kind, default in USER_COLUMNS:
        op.add_column('staff_users', sa.Column(name, kind, nullable=default is None, server_default=default))
    op.add_column('staff_sessions', sa.Column('stage', sa.String(length=8), nullable=False,
                                              server_default=sa.text("'full'")))
    op.add_column('staff_sessions', sa.Column('reauth_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table('staff_recovery_codes',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('hospital_id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'],
                            name=op.f('fk_staff_recovery_codes_hospital_id_hospitals'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['staff_users.id'],
                            name=op.f('fk_staff_recovery_codes_user_id_staff_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_staff_recovery_codes'))
    )
    op.create_index(op.f('ix_staff_recovery_codes_hospital_id'), 'staff_recovery_codes', ['hospital_id'],
                    unique=False)
    op.create_index('ix_staff_recovery_codes_user', 'staff_recovery_codes', ['user_id'], unique=False)
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in install_statements():
        op.execute(statement)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for statement in drop_statements():
            op.execute(statement)
    op.drop_table('staff_recovery_codes')
    # A batch on SQLite rebuilds the tables (dropping a column).
    with op.batch_alter_table('staff_sessions') as batch:
        batch.drop_column('reauth_at')
        batch.drop_column('stage')
    with op.batch_alter_table('staff_users') as batch:
        for name, _kind, _default in reversed(USER_COLUMNS):
            batch.drop_column(name)
