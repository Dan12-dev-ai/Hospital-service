"""Records patients share with this hospital through Endod (docs/history-events.md, section 5).

``records.shared`` stores a read-only copy; ``records.unshared`` (also sent
by the platform at ``expires_at``) deletes it. The copy is also dropped here
once ``expires_at`` passes, whether or not that event has arrived. A share's
files are not copied: they are fetched from the platform on demand.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import AwareDatetime, BaseModel, Field, ValidationError
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app import files
from app.config import get_settings
from app.db import ensure_aware, utcnow
from app.eventbus import PermanentEventError
from app.models import Hospital, RecordCategory, RecordShare, SharedRecord
from app.records import DetailsError, clean_details
from app.validation import normalize_dedan_id

logger = logging.getLogger("hospital.sharing")

HexId = Field(pattern=r"^[0-9a-f]{32}$")
#: Withdrawn shares are remembered this long (so a late "shared" is not stored).
KEEP_TOMBSTONES_FOR = timedelta(days=30)


class _File(BaseModel):
    file_id: str = HexId
    filename: str = Field(min_length=1, max_length=160)
    content_type: str = Field(max_length=40)
    size: int = Field(ge=1, le=files.MAX_FILE_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _Record(BaseModel):
    record_id: str = HexId
    origin: str = Field(min_length=1, max_length=160)
    category: str
    title: str = Field(min_length=1, max_length=200)
    details: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: AwareDatetime
    recorded_by: Optional[str] = Field(default=None, max_length=160)
    files: List[_File] = Field(default_factory=list, max_length=files.MAX_FILES_PER_RECORD)


class Shared(BaseModel):
    share_id: str = HexId
    hospital_id: str = Field(min_length=1, max_length=32)
    dedan_id: str = Field(min_length=1, max_length=16)
    patient_name: str = Field(min_length=1, max_length=160)
    expires_at: Optional[AwareDatetime] = None
    records: List[_Record] = Field(max_length=500)


class Unshared(BaseModel):
    share_id: str = HexId
    hospital_id: str = Field(min_length=1, max_length=32)


def _parse(model, payload: Dict[str, Any]):
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise PermanentEventError(str(exc).splitlines()[0]) from exc


def on_shared(session: Session, payload: Dict[str, Any]) -> None:
    share = _parse(Shared, payload)
    try:
        dedan_id = normalize_dedan_id(share.dedan_id)
    except ValueError as exc:
        raise PermanentEventError(str(exc)) from exc
    if session.get(Hospital, share.hospital_id) is None:
        raise PermanentEventError("unknown hospital")
    copies = []
    for item in share.records:
        if item.category not in RecordCategory.ALL:
            raise PermanentEventError(f"unknown category {item.category!r}")
        try:
            details = clean_details(item.category, item.details)
        except DetailsError:
            # Self-reported records may be sparse: keep what is there, as the patient wrote it.
            details = {k: v for k, v in item.details.items() if isinstance(k, str)}
        for f in item.files:
            if f.content_type not in files.ALLOWED:
                raise PermanentEventError(f"file type {f.content_type!r} not allowed")
        copies.append(SharedRecord(
            share_id=share.share_id, record_id=item.record_id, origin=item.origin, category=item.category,
            title=item.title, details=json.dumps(details, ensure_ascii=False),
            occurred_at=item.occurred_at.astimezone(timezone.utc), recorded_by=item.recorded_by,
            files=json.dumps([f.model_dump() for f in item.files]),
        ))
    existing = session.scalar(select(RecordShare).where(RecordShare.id == share.share_id).with_for_update())
    if existing is not None:
        if existing.hospital_id != share.hospital_id:
            raise PermanentEventError("share belongs to another hospital")
        if existing.revoked_at is not None:
            return  # unshared before this arrived: keep nothing
        # A redelivery (or a resend): replace the copy.
        session.execute(delete(SharedRecord).where(SharedRecord.share_id == existing.id))
        record = existing
    else:
        record = RecordShare(id=share.share_id, hospital_id=share.hospital_id)
        session.add(record)
    if share.expires_at is not None and share.expires_at <= datetime.now(timezone.utc):
        record.revoked_at = utcnow()
        record.dedan_id = record.patient_name = None
        return
    record.dedan_id, record.patient_name = dedan_id, share.patient_name
    record.expires_at = share.expires_at.astimezone(timezone.utc) if share.expires_at else None
    session.flush()
    session.add_all(copies)


def on_unshared(session: Session, payload: Dict[str, Any]) -> None:
    ref = _parse(Unshared, payload)
    share = session.scalar(select(RecordShare).where(RecordShare.id == ref.share_id).with_for_update())
    if share is None:
        # Before its "shared" (out of order): remember, so that one is dropped.
        if session.get(Hospital, ref.hospital_id) is None:
            raise PermanentEventError("unknown hospital")
        session.add(RecordShare(id=ref.share_id, hospital_id=ref.hospital_id, revoked_at=utcnow()))
        return
    if share.hospital_id != ref.hospital_id:
        raise PermanentEventError("share belongs to another hospital")
    _revoke(session, share)


def _revoke(session: Session, share: RecordShare) -> None:
    session.execute(delete(SharedRecord).where(SharedRecord.share_id == share.id))
    share.revoked_at = share.revoked_at or utcnow()
    share.dedan_id = share.patient_name = None


HANDLERS = {
    "records.shared": on_shared,
    "records.unshared": on_unshared,
}


def active_filter(now: Optional[datetime] = None):
    now = now or utcnow()
    return (RecordShare.revoked_at.is_(None),
            or_(RecordShare.expires_at.is_(None), RecordShare.expires_at > now))


def expire(session: Session) -> int:
    """Drop the copies of shares past their end, and old tombstones. Returns how many shares ended."""
    now = utcnow()
    ended = list(session.scalars(select(RecordShare).where(
        RecordShare.revoked_at.is_(None), RecordShare.expires_at.is_not(None), RecordShare.expires_at <= now)))
    for share in ended:
        _revoke(session, share)
    session.execute(delete(RecordShare).where(RecordShare.revoked_at.is_not(None),
                                              RecordShare.revoked_at < now - KEEP_TOMBSTONES_FOR))
    return len(ended)


# --- fetching a shared file from the platform ---------------------------------------------

class FetchError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


_HEX = re.compile(r"^[0-9a-f]{32}$")


def fetch_file(share_id: str, file_id: str, expected: Dict[str, Any]) -> Tuple[tempfile.SpooledTemporaryFile, int]:
    """Download a shared file from the platform into a temporary file, checking
    its size, sha256 and type against what the share listed."""
    settings = get_settings()
    if not settings.PLATFORM_API_URL or not settings.PLATFORM_ADMIN_KEY:
        raise FetchError("Shared files are not available: the Endod platform is not configured.", 503)
    if not _HEX.match(share_id) or not _HEX.match(file_id):
        raise FetchError("Unknown file.", 404)
    url = f"{settings.PLATFORM_API_URL.rstrip('/')}/internal/shares/{share_id}/files/{file_id}"
    request = urllib.request.Request(url, headers={"X-Platform-Key": settings.PLATFORM_ADMIN_KEY})
    limit = int(expected["size"])
    out = tempfile.SpooledTemporaryFile(max_size=2 * 1024 * 1024)
    digest = hashlib.sha256()
    size = 0
    try:
        with _open(request) as response:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise FetchError("The shared file did not match what was shared.")
                if size == len(chunk) and files.sniff(chunk[:16]) != expected["content_type"]:
                    raise FetchError("The shared file did not match what was shared.")
                digest.update(chunk)
                out.write(chunk)
    except urllib.error.HTTPError as exc:
        out.close()
        if exc.code in (403, 404, 410):
            raise FetchError("This file is no longer shared.", 404) from exc
        raise FetchError("The Endod platform could not send the file. Try again shortly.") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        out.close()
        raise FetchError("The Endod platform is not reachable. Try again shortly.") from exc
    except FetchError:
        out.close()
        raise
    if size != limit or digest.hexdigest() != expected["sha256"]:
        out.close()
        raise FetchError("The shared file did not match what was shared.")
    out.seek(0)
    return out, size


def _open(request: urllib.request.Request):
    """Opens the platform URL (tests replace this). Redirects are not followed."""
    opener = urllib.request.build_opener(_NoRedirect)
    return opener.open(request, timeout=30)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401
        return None


def share_payload(share: RecordShare, records: List[SharedRecord]) -> Dict[str, Any]:
    from app.records import iso

    return {
        "share_id": share.id, "dedan_id": share.dedan_id, "patient_name": share.patient_name,
        "expires_at": iso(share.expires_at) if share.expires_at else None,
        "received_at": iso(share.received_at),
        "records": [{
            "id": r.id, "record_id": r.record_id, "origin": r.origin, "category": r.category, "title": r.title,
            "details": json.loads(r.details), "occurred_at": iso(r.occurred_at), "recorded_by": r.recorded_by,
            "files": json.loads(r.files),
        } for r in sorted(records, key=lambda r: ensure_aware(r.occurred_at), reverse=True)],
    }
