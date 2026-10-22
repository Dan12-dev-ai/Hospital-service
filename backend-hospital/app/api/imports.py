"""Importing records from a hospital's own system: preview, then confirm
(docs/history-events.md, section 6; the CSV template is in docs/imports.md)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import files, imports, records
from app.auth import Staff, audit, require_roles
from app.db import new_id, session_scope, utcnow
from app.models import ClinicalRecord, Hospital, ImportBatch, Patient, RecordFile, Role

router = APIRouter(prefix="/imports", tags=["imports"])

#: Who imports records: admins and records staff.
IMPORTERS = (Role.ADMIN, Role.RECORDS)
importers = require_roles(*IMPORTERS)
#: A preview must be confirmed within this time.
PREVIEW_VALID_FOR = timedelta(hours=24)


@router.get("/template.csv", response_class=PlainTextResponse)
def csv_template(staff: Staff = Depends(importers)) -> PlainTextResponse:
    return PlainTextResponse(imports.template(), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="endod-import-template.csv"'})


async def _read_limited(request: Request, limit: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(status_code=413, detail=f"An import file can be at most {limit // (1024 * 1024)} MB.")
    return bytes(body)


@router.post("/preview", status_code=status.HTTP_201_CREATED)
async def preview(request: Request, x_filename: Optional[str] = Header(default=None, max_length=600),
                  content_type: Optional[str] = Header(default=None, max_length=200),
                  content_length: Optional[int] = Header(default=None),
                  staff: Staff = Depends(importers)) -> Dict[str, Any]:
    """The file is the request body (FHIR JSON or CSV). Returns what would be
    imported and what is skipped; nothing is saved but the plan."""
    if content_length is not None and content_length > imports.MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="An import file can be at most 10 MB.")
    data = await _read_limited(request, imports.MAX_IMPORT_BYTES)
    filename = unquote(x_filename or "")[:160] or None
    kind = imports.detect((content_type or "").lower(), filename or "", data)
    return await run_in_threadpool(_plan, staff, data, kind, filename)


def _plan(staff: Staff, data: bytes, kind: str, filename: Optional[str]) -> Dict[str, Any]:
    stored = []
    try:
        with session_scope() as session:
            hospital = session.get(Hospital, staff.hospital_id)
            try:
                planner = imports.plan(session, hospital, data, kind)
            except imports.ImportFailed as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            # Inline documents are kept as uploads until the import is confirmed.
            for item in planner.items:
                document = planner.documents.get(item["index"])
                if document is None:
                    continue
                raw, _type, name = document
                file_id = new_id()
                size, sha256, content_type = files.store_bytes(raw, staff.hospital_id, file_id)
                stored.append(file_id)
                session.add(RecordFile(id=file_id, hospital_id=staff.hospital_id, patient_id=item["patient_id"],
                                       filename=name, content_type=content_type, size=size, sha256=sha256,
                                       uploaded_by=staff.id))
                item["file"]["file_id"] = file_id
            batch = ImportBatch(hospital_id=staff.hospital_id, created_by=staff.id, format=kind, filename=filename,
                                plan=json.dumps({"items": planner.items, "skipped": planner.skipped},
                                                ensure_ascii=False))
            session.add(batch)
            session.flush()
            audit(session, staff.hospital_id, staff.id, "import_previewed", "import", batch.id,
                  {"format": kind, "items": len(planner.items), "skipped": len(planner.skipped)})
            return {"import_id": batch.id, "format": kind, "filename": filename,
                    "items": [_summary(i) for i in planner.items], "skipped": planner.skipped}
    except BaseException:
        for file_id in stored:
            files.delete(staff.hospital_id, file_id)
        raise


def _summary(item: Dict[str, Any]) -> Dict[str, Any]:
    return {k: item[k] for k in ("index", "what", "patient", "category", "title", "occurred_at", "recorded_by",
                                 "file")}


@router.post("/{import_id}/confirm")
def confirm(import_id: str, staff: Staff = Depends(importers)) -> Dict[str, Any]:
    """Create the previewed records (each is published to Endod like any other).
    An item already imported (by this preview or another) is skipped."""
    try:
        return _confirm(import_id, staff)
    except IntegrityError as exc:
        # Two confirmations of the same items at the same moment: the unique
        # import key let one through; confirming again skips what it imported.
        raise HTTPException(status_code=409, detail="The same records were being imported at the same time. "
                                                    "Confirm again: what is already imported is skipped.") from exc


def _confirm(import_id: str, staff: Staff) -> Dict[str, Any]:
    with session_scope() as session:
        batch = session.scalar(select(ImportBatch).where(
            ImportBatch.id == import_id, ImportBatch.hospital_id == staff.hospital_id).with_for_update())
        if batch is None:
            raise HTTPException(status_code=404, detail="Import not found.")
        if batch.status != "previewed":
            raise HTTPException(status_code=409, detail="This import was already confirmed.")
        created = batch.created_at if batch.created_at.tzinfo else batch.created_at.replace(tzinfo=timezone.utc)
        if created < utcnow() - PREVIEW_VALID_FOR:
            raise HTTPException(status_code=409, detail="This preview is too old; upload the file again.")
        hospital = session.get(Hospital, staff.hospital_id)
        plan = json.loads(batch.plan)
        imported, skipped = 0, []
        for item in plan["items"]:
            patient = session.scalar(select(Patient).where(Patient.id == item["patient_id"],
                                                           Patient.hospital_id == staff.hospital_id).with_for_update())
            if patient is None or not patient.dedan_id:
                skipped.append({"index": item["index"], "what": item["what"],
                                "reason": "the patient is no longer linked to Endod"})
                continue
            key = item.get("import_key")
            # Checked again here, in the confirming transaction: another preview of
            # the same file may have been confirmed since this one was made.
            if key and imports.already_imported(session, staff.hospital_id, key):
                skipped.append({"index": item["index"], "what": item["what"], "reason": "already imported"})
                continue
            record = ClinicalRecord(
                hospital_id=staff.hospital_id, patient_id=patient.id, category=item["category"], title=item["title"],
                details=json.dumps(item["details"], ensure_ascii=False),
                occurred_at=datetime.fromisoformat(item["occurred_at"]).astimezone(timezone.utc),
                recorded_by=None, recorded_by_name=item["recorded_by"], source="import", version=1,
                import_key=key,
            )
            session.add(record)
            session.flush()
            file_id = (item.get("file") or {}).get("file_id")
            if file_id:
                row = session.scalar(select(RecordFile).where(RecordFile.id == file_id,
                                                              RecordFile.hospital_id == staff.hospital_id,
                                                              RecordFile.record_id.is_(None)))
                if row is None:
                    raise HTTPException(status_code=409, detail="This preview expired; upload the file again.")
                row.record_id = record.id
                session.flush()
            records.publish(session, record, patient, hospital)
            imported += 1
        batch.status, batch.imported_at = "imported", utcnow()
        audit(session, staff.hospital_id, staff.id, "import_confirmed", "import", batch.id,
              {"imported": imported, "skipped": len(skipped)})
        return {"import_id": batch.id, "imported": imported, "skipped": skipped}
