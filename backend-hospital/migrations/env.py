"""Alembic environment: migrates this service's own database.

In production migrations run as the *owner* role (``hospital``, the one-shot
``migrate`` service in deploy/docker-compose.yml) and the API and worker
connect as the *app* role (``hospital_app``), which owns nothing, has no DDL
rights and does not bypass row-level security (app/rls.py).

After every upgrade on PostgreSQL:

* the app role (HOSPITAL_APP_ROLE, default ``hospital_app``) is created if
  it is missing and HOSPITAL_APP_DB_PASSWORD is set, which also works on an
  existing database; its password and attributes (no superuser, no
  BYPASSRLS) are set again each time. Without the role the migration fails:
  it is never skipped silently;
* it is given exactly what it needs (app.rls.grant_app_role): read and
  write on the app tables (rows as the policies allow; the audit log read
  and append only), SELECT on alembic_version, the lookups, and membership
  without INHERIT in ``hospital_platform``.

Running the migrations as the app role itself is refused. On SQLite none of
this applies.
"""

import os
from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  (registers the tables)
from app import rls
from app.db import Base, get_engine

if context.config.config_file_name is not None:
    # Keep the app's loggers (e.g. hospital.crypto) working when migrations run in-process.
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def set_up_app_role(connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    rls.set_up_app_role(connection, os.environ.get("HOSPITAL_APP_ROLE") or rls.APP_ROLE,
                        os.environ.get("HOSPITAL_APP_DB_PASSWORD") or None, target_metadata.tables)


def run_migrations_offline() -> None:
    context.configure(url=str(get_engine().url), target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
            set_up_app_role(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
