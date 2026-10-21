"""Record files on disk (HOSPITAL_FILES_DIR).

Only PDF, JPEG, PNG and WebP are kept, recognised by their first bytes (the
name's extension must agree, but is never trusted on its own). A file lives
at ``<FILES_DIR>/<hospital_id>/<file_id>``: both parts are ids this service
generated (32 hex characters), so no name a user sends ever reaches a path.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote
from typing import AsyncIterator, Dict, Optional, Tuple

from app.config import get_settings

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES_PER_RECORD = 10

#: Content type -> the extensions a file of that type may carry.
ALLOWED: Dict[str, Tuple[str, ...]] = {
    "application/pdf": (".pdf",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/webp": (".webp",),
}

_HEX_ID = re.compile(r"^[0-9a-f]{32}$")


class FileRejected(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def sniff(head: bytes) -> Optional[str]:
    """The content type from the file's first bytes, or None if not allowed."""
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def root() -> Path:
    return Path(get_settings().FILES_DIR).resolve()


def path_for(hospital_id: str, file_id: str) -> Path:
    """Where a file lives. Refuses anything but our own ids, and any path
    that would leave the files directory."""
    if not _HEX_ID.match(hospital_id or "") or not _HEX_ID.match(file_id or ""):
        raise FileRejected("Unknown file.", 404)
    base = root()
    path = (base / hospital_id / file_id).resolve()
    if path.parent.parent != base:
        raise FileRejected("Unknown file.", 404)
    return path


def safe_filename(name: Optional[str], content_type: str) -> str:
    """A display name for the file: no directories, control or quote
    characters, at most 120 characters, with an extension matching its type."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = unicodedata.normalize("NFC", base)
    base = "".join(c for c in base if c.isprintable() and c not in '"<>|*?:;')
    base = re.sub(r"\s+", " ", base).strip(" .")
    stem, ext = os.path.splitext(base)
    allowed = ALLOWED[content_type]
    if ext and ext.lower() not in allowed:
        raise FileRejected(f"{base} is not a {allowed[0][1:].upper()} file by its name, but is one by its content; "
                           "rename it or choose the right file.")
    stem = stem[:100] or "file"
    return f"{stem}{ext.lower() if ext else allowed[0]}"


async def store_stream(chunks: AsyncIterator[bytes], hospital_id: str, file_id: str,
                       max_bytes: int = MAX_FILE_BYTES) -> Tuple[int, str, str]:
    """Write an upload to disk while hashing it. Returns (size, sha256, content type).

    The file is written beside its final place and moved there only once it
    is complete and of an allowed type.
    """
    final = path_for(hospital_id, file_id)
    final.parent.mkdir(parents=True, exist_ok=True)
    partial = final.with_name(final.name + ".part")
    digest = hashlib.sha256()
    size = 0
    head = b""
    try:
        with open(partial, "wb") as out:
            async for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise FileRejected(f"A file can be at most {max_bytes // (1024 * 1024)} MB.", 413)
                if len(head) < 16:
                    head += chunk[:16 - len(head)]
                digest.update(chunk)
                out.write(chunk)
        return _finish(partial, final, size, head, digest)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def store_bytes(data: bytes, hospital_id: str, file_id: str, max_bytes: int = MAX_FILE_BYTES) -> Tuple[int, str, str]:
    if len(data) > max_bytes:
        raise FileRejected(f"A file can be at most {max_bytes // (1024 * 1024)} MB.", 413)
    final = path_for(hospital_id, file_id)
    final.parent.mkdir(parents=True, exist_ok=True)
    partial = final.with_name(final.name + ".part")
    try:
        partial.write_bytes(data)
        return _finish(partial, final, len(data), data[:16], hashlib.sha256(data))
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _finish(partial: Path, final: Path, size: int, head: bytes, digest) -> Tuple[int, str, str]:
    if size == 0:
        raise FileRejected("The file is empty.")
    content_type = sniff(head)
    if content_type is None:
        raise FileRejected("Only PDF, JPEG, PNG or WebP files can be attached.", 415)
    os.replace(partial, final)
    return size, digest.hexdigest(), content_type


def delete(hospital_id: str, file_id: str) -> None:
    try:
        path_for(hospital_id, file_id).unlink(missing_ok=True)
    except FileRejected:
        pass


def content_disposition(filename: str, inline: bool = True) -> str:
    """A Content-Disposition header that survives any file name (RFC 6266)."""
    # Printable ASCII only: a name from elsewhere (a shared file's) must not break the header.
    fallback = "".join(c for c in filename if " " <= c <= "~" and c not in '"\\').strip() or "file"
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
