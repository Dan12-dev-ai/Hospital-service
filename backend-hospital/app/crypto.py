"""Encryption of health data at rest: envelope encryption with AES-256-GCM.

* **Master key (KEK).** 32 random bytes in the file named by
  ``HOSPITAL_MASTER_KEY_FILE`` (mounted read-only into the API and worker
  only). It never reaches the database, the repository or a log. Outside
  development the service refuses to start without it.
* **Data keys (DEK).** Each hospital has its own 32-byte data key, kept in
  ``hospital_keys`` wrapped (AES-256-GCM) under the master key, with a
  version: rotating adds a version and re-encrypts (``python -m app.cli
  rotate-key``). The table is under row-level security like the others, so
  a transaction sees only its own hospital's keys. Unwrapped keys are kept
  in this process's memory for :data:`CACHE_SECONDS` at most.
* **Values** (app/sealing.py) are stored as ``enc:v1:<key version>:`` and the
  base64 of nonce, ciphertext and tag. The associated data binds each value
  to its table, column, row id and hospital: a value copied to another row,
  column or hospital does not decrypt.
* **Files** (app/files.py) are encrypted in chunks of :data:`CHUNK` bytes,
  each with its own random nonce, and associated data naming the hospital,
  the file id, the chunk's index and whether it is the last chunk (so a
  file cut short, or its chunks reordered, does not decrypt).

Nonces are 12 random bytes from the OS for every value and chunk; a data key
is used for far fewer than 2**32 messages (rotate it long before).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Dict, Iterator, Optional, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings

logger = logging.getLogger("hospital.crypto")

KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16
#: How long an unwrapped data key stays in this process's memory.
CACHE_SECONDS = 300
#: Prefix of an encrypted value (format version 1).
PREFIX = "enc:v1:"
#: Plaintext bytes per encrypted file chunk.
CHUNK = 64 * 1024
#: An encrypted file starts with this, the format byte, the key version and the chunk size.
FILE_MAGIC = b"ENDODENC"
FILE_FORMAT = 1
_FILE_HEADER = struct.Struct(">8sBII")
FILE_HEADER_BYTES = _FILE_HEADER.size

#: Development only, never production: a fixed and public key, so a local
#: database stays readable across restarts without a key file.
_DEVELOPMENT_KEY = hashlib.sha256(b"endod-hospital: development master key, public, never for real data").digest()


class CryptoError(RuntimeError):
    """A key is missing or wrong, or data does not decrypt. Messages name
    tables, columns, ids and key versions, never a value or a key."""


@dataclass(frozen=True)
class DataKey:
    """A hospital's unwrapped data key of one version (never printed)."""

    hospital_id: str
    version: int
    secret: bytes = field(repr=False)

    def __repr__(self) -> str:  # never the key itself
        return f"DataKey(hospital_id={self.hospital_id!r}, version={self.version})"


# --- the master key ------------------------------------------------------------------------

_kek_lock = threading.Lock()
_kek_cache: Dict[str, bytes] = {}
_warned_development = False


def _parse_key_file(raw: bytes) -> bytes:
    """32 raw bytes (``openssl rand -out master.key 32``); 64 hex characters or
    base64 of 32 bytes (with or without a newline) are accepted too."""
    if len(raw) == KEY_BYTES:
        return raw
    text = raw.strip()
    try:
        if len(text) == 2 * KEY_BYTES:
            return bytes.fromhex(text.decode("ascii"))
        decoded = base64.b64decode(text, validate=True)
        if len(decoded) == KEY_BYTES:
            return decoded
    except (ValueError, UnicodeDecodeError, binascii.Error):
        pass
    raise CryptoError("HOSPITAL_MASTER_KEY_FILE must hold 32 random bytes (openssl rand -out master.key 32).")


def master_key() -> bytes:
    """The master key (KEK). Read once per file path, then kept in memory."""
    global _warned_development
    settings = get_settings()
    path = settings.MASTER_KEY_FILE
    if path:
        with _kek_lock:
            key = _kek_cache.get(path)
            if key is None:
                try:
                    raw = Path(path).read_bytes()
                except OSError as exc:
                    raise CryptoError(f"The master key file {path} cannot be read ({exc.strerror}).") from None
                key = _kek_cache[path] = _parse_key_file(raw)
            return key
    if settings.ENVIRONMENT == "development":
        if not _warned_development:
            logger.warning("HOSPITAL_MASTER_KEY_FILE is not set: using the public development key "
                           "(development only; never for real patient data)")
            _warned_development = True
        return _DEVELOPMENT_KEY
    raise CryptoError("HOSPITAL_MASTER_KEY_FILE is not set: the service needs its master key outside development "
                      "(README, 'Encryption at rest').")


def check_master_key() -> None:
    """Refuse to start without a usable master key (the API and worker call this)."""
    master_key()


def _kek_id(kek: bytes) -> bytes:
    """Tells master keys apart in the cache (not the key)."""
    return hashlib.sha256(b"endod-hospital kek id" + kek).digest()[:8]


# --- wrapping data keys --------------------------------------------------------------------

def _wrap_aad(hospital_id: str, version: int) -> bytes:
    return f"endod-hospital|hospital_keys|{hospital_id}|{version}".encode()


def wrap(kek: bytes, dek: bytes, hospital_id: str, version: int) -> str:
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(kek).encrypt(nonce, dek, _wrap_aad(hospital_id, version))
    return base64.b64encode(nonce + sealed).decode("ascii")


def unwrap(kek: bytes, wrapped: str, hospital_id: str, version: int) -> bytes:
    try:
        blob = base64.b64decode(wrapped, validate=True)
        dek = AESGCM(kek).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], _wrap_aad(hospital_id, version))
    except (InvalidTag, ValueError, binascii.Error):
        raise CryptoError(f"Data key version {version} of hospital {hospital_id} does not unwrap with this "
                          "master key (wrong HOSPITAL_MASTER_KEY_FILE?).") from None
    if len(dek) != KEY_BYTES:
        raise CryptoError(f"Data key version {version} of hospital {hospital_id} is malformed.")
    return dek


# --- data keys: looked up in hospital_keys, cached briefly ------------------------------------

_dek_lock = threading.Lock()
_dek_cache: Dict[Tuple[bytes, str, int], Tuple[bytes, float]] = {}


def clear_cache() -> None:
    """Forget unwrapped data keys and master keys (tests; after a rotation)."""
    with _dek_lock:
        _dek_cache.clear()
    with _kek_lock:
        _kek_cache.clear()


def _cached(kek: bytes, hospital_id: str, version: int) -> Optional[bytes]:
    now = time.monotonic()
    with _dek_lock:
        hit = _dek_cache.get((_kek_id(kek), hospital_id, version))
        if hit is None:
            return None
        if hit[1] <= now:
            _dek_cache.pop((_kek_id(kek), hospital_id, version), None)
            return None
        return hit[0]


def _remember(kek: bytes, hospital_id: str, version: int, dek: bytes) -> None:
    now = time.monotonic()
    with _dek_lock:
        for key in [k for k, (_d, until) in _dek_cache.items() if until <= now]:
            del _dek_cache[key]
        _dek_cache[(_kek_id(kek), hospital_id, version)] = (dek, now + CACHE_SECONDS)


def _keys_table():
    from app.models import HospitalKey

    return HospitalKey.__table__


def data_key(session: Session, hospital_id: str, version: int) -> DataKey:
    """The hospital's data key of this version (to decrypt). The lookup runs
    in the session's transaction, so row-level security applies to it."""
    kek = master_key()
    dek = _cached(kek, hospital_id, version)
    if dek is None:
        keys = _keys_table()
        wrapped = session.connection().execute(
            select(keys.c.wrapped_key).where(keys.c.hospital_id == hospital_id, keys.c.version == version)).scalar()
        if wrapped is None:
            raise CryptoError(f"Hospital {hospital_id} has no data key version {version} (or it is not visible "
                              "in this transaction).")
        dek = unwrap(kek, wrapped, hospital_id, version)
        _remember(kek, hospital_id, version, dek)
    return DataKey(hospital_id, version, dek)


def _active_row(session: Session, hospital_id: str):
    keys = _keys_table()
    return session.connection().execute(
        select(keys.c.version, keys.c.wrapped_key).where(keys.c.hospital_id == hospital_id, keys.c.active.is_(True))
        .order_by(keys.c.version.desc()).limit(1)).first()


def active_key(session: Session, hospital_id: str) -> DataKey:
    """The hospital's current data key (to encrypt), created on first use."""
    kek = master_key()
    row = _active_row(session, hospital_id)
    if row is None:
        add_key_version(session, hospital_id, activate=True, only_if_none=True)
        row = _active_row(session, hospital_id)
        if row is None:
            raise CryptoError(f"Hospital {hospital_id} has no active data key.")
    version, wrapped = row
    dek = _cached(kek, hospital_id, version)
    if dek is None:
        dek = unwrap(kek, wrapped, hospital_id, version)
        _remember(kek, hospital_id, version, dek)
    return DataKey(hospital_id, version, dek)


def add_key_version(session: Session, hospital_id: str, activate: bool = True, only_if_none: bool = False) -> int:
    """A new random data key for the hospital (version: one more than the
    highest). With ``only_if_none`` (the first key, created lazily), two
    transactions racing to create it end up with one key: the loser's
    insert is skipped on the unique (hospital_id, version)."""
    from sqlalchemy import func, update

    from app.db import new_id, utcnow

    keys = _keys_table()
    connection = session.connection()
    highest = connection.execute(select(func.max(keys.c.version)).where(keys.c.hospital_id == hospital_id)).scalar()
    version = (highest or 0) + 1
    values = {"id": new_id(), "hospital_id": hospital_id, "version": version,
              "wrapped_key": wrap(master_key(), os.urandom(KEY_BYTES), hospital_id, version),
              "created_at": utcnow(), "active": activate}
    if only_if_none:
        dialect = connection.dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        connection.execute(insert(keys).values(**values).on_conflict_do_nothing(
            index_elements=["hospital_id", "version"]))
        return version
    if activate:
        connection.execute(update(keys).where(keys.c.hospital_id == hospital_id, keys.c.active.is_(True))
                           .values(active=False))
    connection.execute(keys.insert().values(**values))
    return version


# --- values -------------------------------------------------------------------------------------

def field_aad(table: str, column: str, row_id: str, hospital_id: str, version: int) -> bytes:
    return f"endod-hospital|field|v1|{table}|{column}|{row_id}|{hospital_id}|{version}".encode()


def is_sealed(value: object) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def sealed_version(value: str) -> int:
    """The key version of an encrypted value."""
    try:
        return int(value[len(PREFIX):].split(":", 1)[0])
    except ValueError:
        raise CryptoError("An encrypted value is malformed.") from None


def seal(key: DataKey, plaintext: str, table: str, column: str, row_id: str) -> str:
    nonce = os.urandom(NONCE_BYTES)
    aad = field_aad(table, column, row_id, key.hospital_id, key.version)
    sealed = AESGCM(key.secret).encrypt(nonce, plaintext.encode("utf-8"), aad)
    return f"{PREFIX}{key.version}:{base64.b64encode(nonce + sealed).decode('ascii')}"


def unseal(key: DataKey, value: str, table: str, column: str, row_id: str) -> str:
    where = f"{table}.{column} of row {row_id}"
    version = sealed_version(value)
    if version != key.version:
        raise CryptoError(f"{where} is encrypted with key version {version}, not {key.version}.")
    try:
        blob = base64.b64decode(value[len(PREFIX):].split(":", 1)[1], validate=True)
        if len(blob) < NONCE_BYTES + TAG_BYTES:
            raise ValueError("too short")
        aad = field_aad(table, column, row_id, key.hospital_id, key.version)
        return AESGCM(key.secret).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], aad).decode("utf-8")
    except (InvalidTag, ValueError, IndexError, binascii.Error, UnicodeDecodeError):
        raise CryptoError(f"{where} does not decrypt (wrong key, or moved from another row or hospital).") from None


# --- files ----------------------------------------------------------------------------------------

def _chunk_aad(header: bytes, hospital_id: str, file_id: str, index: int, final: bool) -> bytes:
    return header + f"|endod-hospital|file|{hospital_id}|{file_id}|{index}|{int(final)}".encode()


class FileSealer:
    """Encrypts a file as it arrives: :meth:`header`, then :meth:`update`
    with each piece, then :meth:`finish` (the last chunk, possibly empty)."""

    def __init__(self, key: DataKey, file_id: str):
        self.key, self.file_id = key, file_id
        self._aes = AESGCM(key.secret)
        self._header = _FILE_HEADER.pack(FILE_MAGIC, FILE_FORMAT, key.version, CHUNK)
        self._buffer = bytearray()
        self._index = 0

    def header(self) -> bytes:
        return self._header

    def _seal(self, data: bytes, final: bool) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        aad = _chunk_aad(self._header, self.key.hospital_id, self.file_id, self._index, final)
        self._index += 1
        return nonce + self._aes.encrypt(nonce, bytes(data), aad)

    def update(self, data: bytes) -> bytes:
        self._buffer += data
        out = []
        # A full chunk is sealed only once more data follows it: the last chunk is marked final.
        while len(self._buffer) > CHUNK:
            out.append(self._seal(self._buffer[:CHUNK], final=False))
            del self._buffer[:CHUNK]
        return b"".join(out)

    def finish(self) -> bytes:
        last = self._seal(self._buffer, final=True)
        self._buffer = bytearray()
        return last


def read_file_header(handle: BinaryIO) -> Optional[Tuple[int, bytes]]:
    """(key version, header) of an encrypted file, or None for a plaintext one
    (stored before encryption; read from the start again)."""
    header = handle.read(FILE_HEADER_BYTES)
    if len(header) == FILE_HEADER_BYTES and header.startswith(FILE_MAGIC):
        _magic, fmt, version, chunk = _FILE_HEADER.unpack(header)
        if fmt != FILE_FORMAT or chunk != CHUNK:
            raise CryptoError("An encrypted file has an unknown format.")
        return version, header
    handle.seek(0)
    return None


def open_chunks(handle: BinaryIO, key: DataKey, header: bytes, file_id: str) -> Iterator[bytes]:
    """The plaintext of an encrypted file (positioned after its header), chunk
    by chunk. Raises CryptoError if any chunk is wrong, missing or out of place."""
    aes = AESGCM(key.secret)
    record = NONCE_BYTES + CHUNK + TAG_BYTES
    index = 0
    current = handle.read(record)
    while True:
        following = handle.read(record) if len(current) == record else b""
        final = not following
        if len(current) < NONCE_BYTES + TAG_BYTES:
            raise CryptoError(f"File {file_id} is cut short.")
        try:
            plain = aes.decrypt(current[:NONCE_BYTES], current[NONCE_BYTES:],
                                _chunk_aad(header, key.hospital_id, file_id, index, final))
        except InvalidTag:
            raise CryptoError(f"File {file_id} does not decrypt at chunk {index} (wrong key, altered, cut short "
                              "or moved).") from None
        yield plain
        if final:
            return
        index += 1
        current = following
