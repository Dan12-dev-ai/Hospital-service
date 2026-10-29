"""Database engine and sessions.

This service has its own database. It never reads or writes the patient
platform's database; the two exchange data only through their APIs.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from sqlalchemy import MetaData, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DisconnectionError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

DEV_DATABASE_URL = "sqlite:///./hospital.db"


class Base(DeclarativeBase):
    # Explicit constraint names: the same on SQLite and PostgreSQL, so later
    # migrations can alter them by name on both.
    metadata = MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


def ensure_aware(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes; everything here is UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


_engine: Optional[Engine] = None
_engine_url: Optional[str] = None
_sessions: Optional[sessionmaker] = None


def database_url() -> str:
    settings = get_settings()
    url = settings.DATABASE_URL or ""
    if settings.is_production and (not url or url.startswith("sqlite")):
        raise RuntimeError("HOSPITAL_DATABASE_URL must point at PostgreSQL in production.")
    if not url and settings.ENVIRONMENT != "development":
        # A container that lost its URL must not quietly use a throwaway SQLite file.
        raise RuntimeError("HOSPITAL_DATABASE_URL is not set.")
    return url or DEV_DATABASE_URL


#: The PostgreSQL application_name of this process's connections; the CLI
#: sets :data:`CLI_APPLICATION_NAME` before it connects.
APPLICATION_NAME = "hospital-app"
CLI_APPLICATION_NAME = "hospital-cli"


def get_engine() -> Engine:
    global _engine, _engine_url, _sessions
    url = database_url()
    if _engine is None or url != _engine_url:
        # Errors (and the tracebacks in logs) never show statement parameters:
        # they may be health data.
        kwargs = {"pool_pre_ping": True, "hide_parameters": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        elif url.startswith("postgresql"):
            # Names this process's connections (app/rekey.py tells the API and
            # worker apart from the CLI by it).
            kwargs["connect_args"] = {"application_name": APPLICATION_NAME}
        _engine = create_engine(url, **kwargs)
        if _engine.dialect.name == "postgresql":
            event.listen(_engine, "checkout", _clean_connection)
        if url.startswith("sqlite"):
            # SQLite ignores foreign keys unless asked, which would hide
            # integrity bugs in development and tests.
            event.listen(_engine, "connect", _sqlite_foreign_keys)
        _engine_url = url
        _sessions = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def _clean_connection(dbapi_connection, _record, _proxy) -> None:
    """Every checkout starts from the login role with default settings: a
    session-level SET ROLE or SET (not LOCAL) by an earlier user of this pooled
    connection never carries over. A connection that cannot be reset is
    replaced (DisconnectionError makes the pool try another)."""
    try:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("RESET ROLE; RESET ALL")
        finally:
            cursor.close()
        dbapi_connection.commit()
    except Exception as exc:  # noqa: BLE001
        raise DisconnectionError(f"could not reset a pooled connection: {exc}") from exc


def _sqlite_foreign_keys(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def reset_engine() -> None:
    global _engine, _engine_url, _sessions
    if _engine is not None:
        _engine.dispose()
    _engine = _engine_url = _sessions = None


# --- Tenant context (PostgreSQL row-level security; see app/rls.py) -----------------------
#
# Every transaction starts by setting ``app.hospital_id`` (the tenant the
# policies compare with) for itself only (``set_config(..., true)``, i.e. SET
# LOCAL), in ``after_begin``: a transaction begun again after a commit inside a
# ``with`` block gets it too, and it never outlives the transaction on a
# pooled connection. A platform transaction instead takes the
# ``hospital_platform`` role for itself (SET LOCAL ROLE). With neither, the
# policies show no rows and refuse every write: it fails closed.

TENANT_KEY = "hospital_id"
SCOPE_KEY = "scope"
PLATFORM = "platform"
PLATFORM_ROLE = "hospital_platform"


@event.listens_for(Session, "after_begin")
def _apply_tenant(session: Session, _transaction, connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.execute(text("SELECT set_config('app.hospital_id', :tenant, true)"),
                       {"tenant": session.info.get(TENANT_KEY) or ""})
    if session.info.get(SCOPE_KEY) == PLATFORM:
        connection.exec_driver_sql(f"SET LOCAL ROLE {PLATFORM_ROLE}")


def set_tenant(session: Session, hospital_id: Optional[str]) -> None:
    """Make ``hospital_id`` the tenant of this session from now on (sign-in,
    which learns the hospital from its first lookup)."""
    session.info[TENANT_KEY] = hospital_id or ""
    if session.in_transaction() and session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT set_config('app.hospital_id', :tenant, true)"), {"tenant": hospital_id or ""})


@contextmanager
def _scope(hospital_id: Optional[str], scope: str) -> Iterator[Session]:
    get_engine()
    session = _sessions(info={TENANT_KEY: hospital_id or "", SCOPE_KEY: scope})
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def session_scope(hospital_id: Optional[str] = None):
    """A transaction for one hospital: the database shows and accepts only
    that hospital's rows. Pass the signed-in staff member's ``hospital_id``.

    Without one, no hospital's rows are visible (enough for the tables that
    belong to no hospital, such as the event outbox).
    """
    return _scope(hospital_id, "")


def platform_session():
    """A transaction acting for Endod across hospitals, as the
    ``hospital_platform`` role: ``/platform`` routes (X-Platform-Key), events
    from the bus, the worker's chores and the CLI. Never for a staff request,
    nor for any request that is not authenticated."""
    return _scope(None, PLATFORM)


def check_connection_role() -> None:
    """Refuse to run the API or worker as a role the policies do not hold:
    a superuser, one with BYPASSRLS, or the tables' owner."""
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        return
    from app.rls import connection_role_problem

    with engine.connect() as connection:
        problem = connection_role_problem(connection)
        user = connection.execute(text("SELECT current_user")).scalar()
    if problem:
        raise RuntimeError(f"The database login {user!r} {problem}: connect as the app role (hospital_app), "
                           "so row-level security applies.")


def create_all() -> None:
    """Create tables directly (tests and local development).

    Deployments use the Alembic migrations in ``migrations/`` instead.
    """
    from app import models  # noqa: F401  (registers the tables)

    Base.metadata.create_all(get_engine())
