"""Periodic clean-up for patient history (run by the worker)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select

from app import files, sharing
from app.db import session_scope, utcnow
from app.models import ImportBatch, RecordFile

#: Uploads never attached to a record (an abandoned form or import preview).
KEEP_UNATTACHED_FOR = timedelta(days=2)
KEEP_IMPORT_PLANS_FOR = timedelta(days=30)


def run() -> int:
    """End expired shares, delete abandoned uploads and old import plans. Returns the work done."""
    now = utcnow()
    with session_scope() as session:
        work = sharing.expire(session)
        for row in session.scalars(select(RecordFile).where(
                RecordFile.record_id.is_(None), RecordFile.created_at < now - KEEP_UNATTACHED_FOR)):
            files.delete(row.hospital_id, row.id)
            session.delete(row)
            work += 1
        session.execute(delete(ImportBatch).where(ImportBatch.created_at < now - KEEP_IMPORT_PLANS_FOR))
    return work
