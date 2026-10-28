"""integration API: clients, used assertions, request log, resources, idempotency, webhook deliveries

The tables of the integration API for hospitals' own systems
(app/integrations, docs/integrations.md):

* ``integration_clients``: connected systems (OAuth 2.0 client credentials;
  an argon2 hash of the secret, or public keys; the webhook URL and its
  secret, encrypted at rest);
* ``integration_assertions``: the ``jti`` of each client assertion used,
  until it expires (each is used once);
* ``integration_requests``: the request log (no bodies, kept 30 days);
* ``integration_resources``: which record each FHIR resource became (by the
  client's resource id), for corrections;
* ``integration_idempotency``: answers replayed for an Idempotency-Key;
* ``webhook_deliveries``: events waiting for, or sent to, a client's webhook.

Every table belongs to a hospital and, on PostgreSQL, gets row-level security
like the others (ENABLE, FORCE, ``tenant_isolation`` and ``platform_access``),
composite foreign keys to rows of its own hospital, and the token endpoint's
lookup ``hospital_of_integration_client``. The definitions are frozen copies
of app/rls.py at this revision (tests/test_rls.py checks they agree).

Downgrading drops the tables (every connection stops working); nothing else
is touched.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-28 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

PLATFORM_ROLE = "hospital_platform"
TENANT_TABLES = [
    ("integration_clients", "hospital_id"),
    ("integration_assertions", "hospital_id"),
    ("integration_requests", "hospital_id"),
    ("integration_resources", "hospital_id"),
    ("integration_idempotency", "hospital_id"),
    ("webhook_deliveries", "hospital_id"),
]
SAME_HOSPITAL_REFERENCES = [
    ("integration_clients", "created_by", "staff_users", "SET NULL"),
    ("integration_assertions", "client_pk", "integration_clients", "CASCADE"),
    ("integration_requests", "client_pk", "integration_clients", "CASCADE"),
    ("integration_resources", "client_pk", "integration_clients", "CASCADE"),
    ("integration_resources", "record_id", "clinical_records", "CASCADE"),
    ("integration_idempotency", "client_pk", "integration_clients", "CASCADE"),
    ("webhook_deliveries", "client_pk", "integration_clients", "CASCADE"),
]
#: Parents first referred to by a composite key at this revision (the others got their unique key in 0007).
NEW_PARENTS = ["integration_clients"]
TENANT_POLICY = "tenant_isolation"
PLATFORM_POLICY = "platform_access"
TENANT = "current_setting('app.hospital_id', true)"
_DEFINER = "SECURITY DEFINER SET search_path = public, pg_temp"
FUNCTIONS = [
    ("hospital_of_integration_client(p_client_id text)",
     f"""RETURNS text LANGUAGE sql STABLE {_DEFINER} AS $$
        SELECT hospital_id::text FROM integration_clients WHERE client_id = p_client_id $$"""),
]


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
    statements = [f"ALTER TABLE {child} DROP CONSTRAINT IF EXISTS {_fk(child, column)}"
                  for child, column, _p, _d in SAME_HOSPITAL_REFERENCES]
    for parent in NEW_PARENTS:
        statements += [f"ALTER TABLE {parent} DROP CONSTRAINT IF EXISTS {_unique(parent)}",
                       f"ALTER TABLE {parent} ADD CONSTRAINT {_unique(parent)} UNIQUE (hospital_id, id)"]
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
    for (signature, body), name in zip(FUNCTIONS, _function_names()):
        statements += [f"CREATE OR REPLACE FUNCTION {signature} {body}",
                       f"ALTER FUNCTION {name} OWNER TO {PLATFORM_ROLE}",
                       f"REVOKE ALL ON FUNCTION {name} FROM PUBLIC"]
    return statements


def drop_statements():
    statements = [f"DROP FUNCTION IF EXISTS {name}" for name in _function_names()]
    for table, _column in TENANT_TABLES:
        statements += [
            f"DROP POLICY IF EXISTS {PLATFORM_POLICY} ON {table}",
            f"DROP POLICY IF EXISTS {TENANT_POLICY} ON {table}",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
        ]
    statements += [f"ALTER TABLE {child} DROP CONSTRAINT IF EXISTS {_fk(child, column)}"
                   for child, column, _p, _d in SAME_HOSPITAL_REFERENCES]
    statements += [f"ALTER TABLE {parent} DROP CONSTRAINT IF EXISTS {_unique(parent)}" for parent in NEW_PARENTS]
    return statements


def _id():
    return sa.Column('id', sa.String(length=32), nullable=False)


def _hospital(table):
    return (sa.Column('hospital_id', sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], name=op.f(f'fk_{table}_hospital_id_hospitals'),
                                    ondelete='CASCADE'))


def _client(table):
    return (sa.Column('client_pk', sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(['client_pk'], ['integration_clients.id'],
                                    name=op.f(f'fk_{table}_client_pk_integration_clients'), ondelete='CASCADE'))


def _when(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    hospital, hospital_fk = _hospital('integration_clients')
    op.create_table('integration_clients',
    _id(), hospital,
    sa.Column('client_id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('scopes', sa.String(length=400), nullable=False),
    sa.Column('mode', sa.String(length=4), nullable=False),
    sa.Column('auth_method', sa.String(length=20), nullable=False),
    sa.Column('secret_hash', sa.String(length=255), nullable=True),
    sa.Column('jwks', sa.Text(), nullable=True),
    sa.Column('allowed_cidrs', sa.String(length=2000), nullable=True),
    sa.Column('webhook_url', sa.String(length=500), nullable=True),
    sa.Column('webhook_secret', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(length=32), nullable=True),
    _when('created_at'), _when('last_used_at', True), _when('credentials_changed_at', True),
    _when('revoked_at', True),
    hospital_fk,
    sa.ForeignKeyConstraint(['created_by'], ['staff_users.id'], name=op.f('fk_integration_clients_created_by_staff_users'),
                            ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_integration_clients')),
    sa.UniqueConstraint('client_id', name=op.f('uq_integration_clients_client_id'))
    )
    op.create_index(op.f('ix_integration_clients_hospital_id'), 'integration_clients', ['hospital_id'], unique=False)

    hospital, hospital_fk = _hospital('integration_assertions')
    client, client_fk = _client('integration_assertions')
    op.create_table('integration_assertions',
    _id(), hospital, client,
    sa.Column('jti', sa.String(length=255), nullable=False),
    _when('expires_at'),
    hospital_fk, client_fk,
    sa.PrimaryKeyConstraint('id', name=op.f('pk_integration_assertions')),
    sa.UniqueConstraint('client_pk', 'jti', name='uq_integration_assertion_jti')
    )
    op.create_index(op.f('ix_integration_assertions_hospital_id'), 'integration_assertions', ['hospital_id'],
                    unique=False)

    hospital, hospital_fk = _hospital('integration_requests')
    client, client_fk = _client('integration_requests')
    op.create_table('integration_requests',
    _id(), hospital, client,
    sa.Column('method', sa.String(length=8), nullable=False),
    sa.Column('path', sa.String(length=300), nullable=False),
    sa.Column('status', sa.Integer(), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    _when('at'),
    hospital_fk, client_fk,
    sa.PrimaryKeyConstraint('id', name=op.f('pk_integration_requests'))
    )
    op.create_index(op.f('ix_integration_requests_hospital_id'), 'integration_requests', ['hospital_id'],
                    unique=False)
    op.create_index('ix_integration_requests_client_at', 'integration_requests', ['client_pk', 'at'], unique=False)

    hospital, hospital_fk = _hospital('integration_resources')
    client, client_fk = _client('integration_resources')
    op.create_table('integration_resources',
    _id(), hospital, client,
    sa.Column('resource_type', sa.String(length=40), nullable=False),
    sa.Column('resource_id', sa.String(length=64), nullable=False),
    sa.Column('version_id', sa.String(length=64), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('record_id', sa.String(length=32), nullable=False),
    _when('created_at'), _when('updated_at'),
    hospital_fk, client_fk,
    sa.ForeignKeyConstraint(['record_id'], ['clinical_records.id'],
                            name=op.f('fk_integration_resources_record_id_clinical_records'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_integration_resources')),
    sa.UniqueConstraint('client_pk', 'resource_type', 'resource_id', name='uq_integration_resource')
    )
    op.create_index(op.f('ix_integration_resources_hospital_id'), 'integration_resources', ['hospital_id'],
                    unique=False)

    hospital, hospital_fk = _hospital('integration_idempotency')
    client, client_fk = _client('integration_idempotency')
    op.create_table('integration_idempotency',
    _id(), hospital, client,
    sa.Column('key', sa.String(length=255), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=False),
    sa.Column('response', sa.Text(), nullable=False),
    _when('created_at'),
    hospital_fk, client_fk,
    sa.PrimaryKeyConstraint('id', name=op.f('pk_integration_idempotency')),
    sa.UniqueConstraint('client_pk', 'key', name='uq_integration_idempotency_key')
    )
    op.create_index(op.f('ix_integration_idempotency_hospital_id'), 'integration_idempotency', ['hospital_id'],
                    unique=False)

    hospital, hospital_fk = _hospital('webhook_deliveries')
    client, client_fk = _client('webhook_deliveries')
    op.create_table('webhook_deliveries',
    _id(), hospital, client,
    sa.Column('event_id', sa.String(length=40), nullable=False),
    sa.Column('event_type', sa.String(length=40), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    _when('next_attempt_at', True), _when('last_attempt_at', True),
    sa.Column('last_status_code', sa.Integer(), nullable=True),
    sa.Column('last_error', sa.String(length=200), nullable=True),
    _when('created_at'), _when('delivered_at', True),
    hospital_fk, client_fk,
    sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_deliveries'))
    )
    op.create_index(op.f('ix_webhook_deliveries_hospital_id'), 'webhook_deliveries', ['hospital_id'], unique=False)
    op.create_index('ix_webhook_deliveries_due', 'webhook_deliveries', ['status', 'next_attempt_at'], unique=False)
    op.create_index('ix_webhook_deliveries_client', 'webhook_deliveries', ['client_pk', 'created_at'], unique=False)

    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in install_statements():
        op.execute(statement)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for statement in drop_statements():
            op.execute(statement)
    for table in ('webhook_deliveries', 'integration_idempotency', 'integration_resources', 'integration_requests',
                  'integration_assertions'):
        op.drop_table(table)  # their indexes go with them
    op.drop_table('integration_clients')
