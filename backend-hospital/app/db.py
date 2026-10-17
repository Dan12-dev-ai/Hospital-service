"""Database engine and sessions.

This service has its own database. It never reads or writes the patient
platform's database; the two exchange data only through their APIs.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import Engine
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


def get_engine() -> Engine:
    global _engine, _engine_url, _sessions
    url = database_url()
    if _engine is None or url != _engine_url:
        kwargs = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            # SQLite ignores foreign keys unless asked, which would hide
            # integrity bugs in development and tests.
            event.listen(_engine, "connect", _sqlite_foreign_keys)
        _engine_url = url
        _sessions = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def _sqlite_foreign_keys(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def reset_engine() -> None:
    global _engine, _engine_url, _sessions
    if _engine is not None:
        _engine.dispose()
    _engine = _engine_url = _sessions = None


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    session = _sessions()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all() -> None:
    """Create tables directly (tests and local development).

    Deployments use the Alembic migrations in ``migrations/`` instead.
    """
    from app import models  # noqa: F401  (registers the tables)

    Base.metadata.create_all(get_engine())
