"""Record files on disk (HOSPITAL_FILES_DIR).

Only PDF, JPEG, PNG and WebP are kept, recognised by their first bytes (the
name's extension must agree, but is never trusted on its own). A file lives
at ``<FILES_DIR>/<hospital_id>/<file_id>``: both parts are ids this service
generated (32 hex characters), so no name a user sends ever reaches a path.

Files are encrypted at rest with their hospital's data key (app/crypto.py:
AES-256-GCM in 64 KiB chunks): encrypted as they arrive, decrypted as they
are sent. Size, type and sha256 are those of the plain file; the sha256 is
checked on every read, before the first byte is sent. A file stored before
encryption (no header) is still read, and checked, as it is, until
``python -m app.cli encrypt-existing`` encrypts it.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote
from typing import AsyncIterator, BinaryIO, Dict, Iterable, Iterator, Optional, Tuple

from app import crypto
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


class FileDamaged(crypto.CryptoError):
    """The file on disk does not decrypt, or is not the file that was stored."""


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


# --- storing (always encrypted) -------------------------------------------------------------

def _check_key(key: crypto.DataKey, hospital_id: str) -> None:
    if key.hospital_id != hospital_id:
        raise crypto.CryptoError("A file must be encrypted with its own hospital's key.")


async def store_stream(chunks: AsyncIterator[bytes], hospital_id: str, file_id: str, key: crypto.DataKey,
                       max_bytes: int = MAX_FILE_BYTES) -> Tuple[int, str, str]:
    """Encrypt an upload to disk while hashing its plain bytes. Returns
    (size, sha256, content type) of the plain file. ``key`` is the
    hospital's active data key (:func:`app.crypto.active_key`).

    The file is written beside its final place and moved there only once it
    is complete and of an allowed type.
    """
    _check_key(key, hospital_id)
    final = path_for(hospital_id, file_id)
    final.parent.mkdir(parents=True, exist_ok=True)
    partial = final.with_name(final.name + ".part")
    digest = hashlib.sha256()
    sealer = crypto.FileSealer(key, file_id)
    size = 0
    head = b""
    try:
        with open(partial, "wb") as out:
            out.write(sealer.header())
            async for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise FileRejected(f"A file can be at most {max_bytes // (1024 * 1024)} MB.", 413)
                if len(head) < 16:
                    head += chunk[:16 - len(head)]
                digest.update(chunk)
                out.write(sealer.update(chunk))
            out.write(sealer.finish())
        return _finish(partial, final, size, head, digest)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def store_bytes(data: bytes, hospital_id: str, file_id: str, key: crypto.DataKey,
                max_bytes: int = MAX_FILE_BYTES) -> Tuple[int, str, str]:
    if len(data) > max_bytes:
        raise FileRejected(f"A file can be at most {max_bytes // (1024 * 1024)} MB.", 413)
    _check_key(key, hospital_id)
    final = path_for(hospital_id, file_id)
    final.parent.mkdir(parents=True, exist_ok=True)
    partial = final.with_name(final.name + ".part")
    try:
        write_sealed(partial, [data], key, file_id)
        return _finish(partial, final, len(data), data[:16], hashlib.sha256(data))
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def write_sealed(path: Path, pieces: Iterable[bytes], key: crypto.DataKey, file_id: str) -> None:
    """Write the plain ``pieces`` to ``path``, encrypted."""
    sealer = crypto.FileSealer(key, file_id)
    with open(path, "wb") as out:
        out.write(sealer.header())
        for piece in pieces:
            out.write(sealer.update(piece))
        out.write(sealer.finish())
        out.flush()
        os.fsync(out.fileno())


def _finish(partial: Path, final: Path, size: int, head: bytes, digest) -> Tuple[int, str, str]:
    if size == 0:
        raise FileRejected("The file is empty.")
    content_type = sniff(head)
    if content_type is None:
        raise FileRejected("Only PDF, JPEG, PNG or WebP files can be attached.", 415)
    os.replace(partial, final)
    return size, digest.hexdigest(), content_type


# --- reading -----------------------------------------------------------------------------------

def plain_pieces(handle: BinaryIO, key: Optional[crypto.DataKey], header: Optional[bytes],
                 file_id: str) -> Iterator[bytes]:
    """The plain bytes of an opened file, positioned after its header (or at
    the start of a file stored before encryption: ``header`` None)."""
    if header is None:
        while True:
            piece = handle.read(crypto.CHUNK)
            if not piece:
                return
            yield piece
    else:
        yield from crypto.open_chunks(handle, key, header, file_id)


class PlainFile:
    """An opened and checked file: iterate it once for its plain bytes (the
    file is closed at the end, or by :meth:`close`)."""

    def __init__(self, handle: BinaryIO, key: Optional[crypto.DataKey], header: Optional[bytes], file_id: str,
                 size: int):
        self._handle, self._key, self._header, self._file_id = handle, key, header, file_id
        self.size = size

    def __iter__(self) -> Iterator[bytes]:
        try:
            self._handle.seek(crypto.FILE_HEADER_BYTES if self._header is not None else 0)
            yield from plain_pieces(self._handle, self._key, self._header, self._file_id)
        finally:
            self.close()

    def close(self) -> None:
        self._handle.close()


def open_file(session, hospital_id: str, file_id: str) -> Tuple[BinaryIO, Optional[crypto.DataKey], Optional[bytes]]:
    """(handle, key, header) of a stored file; key and header are None for a
    file stored before encryption. Raises FileRejected (404) if missing."""
    path = path_for(hospital_id, file_id)
    try:
        handle = open(path, "rb")
    except FileNotFoundError:
        raise FileRejected("Unknown file.", 404) from None
    try:
        found = crypto.read_file_header(handle)
        if found is None:
            return handle, None, None
        version, header = found
        return handle, crypto.data_key(session, hospital_id, version), header
    except BaseException:
        handle.close()
        raise


def open_checked(session, hospital_id: str, file_id: str, size: int, sha256: str) -> PlainFile:
    """Open a stored file to send it: decrypted (with the key version its
    header names, looked up in ``session``) and checked against the stored
    size and sha256 of the plain file before anything is sent. Raises
    FileRejected (404) if it is missing, FileDamaged if it does not match."""
    handle, key, header = open_file(session, hospital_id, file_id)
    try:
        digest, seen = hashlib.sha256(), 0
        for piece in plain_pieces(handle, key, header, file_id):
            digest.update(piece)
            seen += len(piece)
        if seen != size or not hmac.compare_digest(digest.hexdigest(), sha256):
            raise FileDamaged(f"File {file_id} does not match its stored sha256.")
        return PlainFile(handle, key, header, file_id, seen)
    except BaseException:
        handle.close()
        raise


def streaming_response(plain: PlainFile, media_type: str, filename: str, sha256: str):
    """The file as an HTTP response (inline, never sniffed, never cached)."""
    from starlette.responses import StreamingResponse

    return StreamingResponse(iter(plain), media_type=media_type, headers={
        "Content-Length": str(plain.size), "Content-Disposition": content_disposition(filename),
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store", "X-Sha256": sha256,
    })


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
