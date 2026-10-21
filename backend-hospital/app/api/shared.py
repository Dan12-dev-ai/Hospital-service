"""Records patients shared with this hospital through Endod: read-only,
showing where each came from (docs/history-events.md, section 5)."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app import files, sharing
from app.api.history import RECORD_READERS
from app.auth import Staff, audit, require_roles
from app.db import session_scope
from app.models import Patient, RecordShare, SharedRecord

router = APIRouter(prefix="/shared", tags=["shared records"])
readers = require_roles(*RECORD_READERS)


@router.get("")
def list_shared(patient_id: Optional[str] = Query(default=None, max_length=32),
                staff: Staff = Depends(readers)) -> Dict[str, Any]:
    """Every active share (or one patient's), newest first, each with the
    hospital patient it belongs to when that patient is linked here."""
    with session_scope() as session:
        query = select(RecordShare).where(RecordShare.hospital_id == staff.hospital_id, *sharing.active_filter())
        if patient_id:
            patient = session.scalar(select(Patient).where(Patient.id == patient_id,
                                                           Patient.hospital_id == staff.hospital_id))
            if patient is None:
                raise HTTPException(status_code=404, detail="Patient not found.")
            if not patient.dedan_id:
                return {"items": []}
            query = query.where(RecordShare.dedan_id == patient.dedan_id)
        shares = list(session.scalars(query.order_by(RecordShare.received_at.desc())))
        dedan_ids = {s.dedan_id for s in shares if s.dedan_id}
        patients = {p.dedan_id: p for p in session.scalars(select(Patient).where(
            Patient.hospital_id == staff.hospital_id, Patient.dedan_id.in_(dedan_ids or {""})))}
        rows: Dict[str, list] = {}
        for record in session.scalars(select(SharedRecord).where(
                SharedRecord.share_id.in_([s.id for s in shares] or [""]))):
            rows.setdefault(record.share_id, []).append(record)
        audit(session, staff.hospital_id, staff.id, "shared_records_viewed", "patient", patient_id)
        items = []
        for share in shares:
            patient = patients.get(share.dedan_id)
            items.append({**sharing.share_payload(share, rows.get(share.id, [])),
                          "patient": {"id": patient.id, "mrn": patient.mrn, "full_name": patient.full_name}
                          if patient else None})
        return {"items": items}


@router.get("/{share_id}/files/{file_id}")
async def shared_file(share_id: str, file_id: str, staff: Staff = Depends(readers)):
    """A shared record's file, fetched from Endod now and passed on (not kept here)."""

    def find() -> Dict[str, Any]:
        with session_scope() as session:
            share = session.scalar(select(RecordShare).where(
                RecordShare.id == share_id, RecordShare.hospital_id == staff.hospital_id, *sharing.active_filter()))
            if share is None:
                raise HTTPException(status_code=404, detail="This file is no longer shared.")
            for record in session.scalars(select(SharedRecord).where(SharedRecord.share_id == share.id)):
                for f in json.loads(record.files):
                    if f.get("file_id") == file_id:
                        audit(session, staff.hospital_id, staff.id, "shared_file_viewed", "record_share", share.id,
                              {"file_id": file_id, "record_id": record.record_id})
                        return f
            raise HTTPException(status_code=404, detail="File not found.")

    listed = await run_in_threadpool(find)
    try:
        body, size = await run_in_threadpool(sharing.fetch_file, share_id, file_id, listed)
    except sharing.FetchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    def chunks():
        try:
            while True:
                chunk = body.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    return StreamingResponse(chunks(), media_type=listed["content_type"], headers={
        "Content-Length": str(size), "Content-Disposition": files.content_disposition(listed["filename"]),
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
    })
