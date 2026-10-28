"""Operator jobs for encryption at rest (``python -m app.cli ...``), run for
Endod across hospitals (platform scope), in batches, each its own transaction:

* :func:`encrypt_existing` encrypts what was stored in plain text before
  encryption (values and files). Safe to stop and run again.
* :func:`check` counts what is still plain text (and what is encrypted with
  a key version that is no longer active).
* :func:`rotate_key` gives a hospital a new data key version and re-encrypts
  its values and files with it (the old version stays, inactive, so nothing
  in flight or in a backup becomes unreadable).
* :func:`decrypt_existing` turns everything back into plain text: only to
  roll back migration 0008 (README, "Encryption at rest").

Rows are changed with Core statements on the ciphertext, each guarded by
the value it read (``WHERE column = <old value>``): a row the app changed
meanwhile is left alone (the app wrote it encrypted already) and picked up
again if it still needs work. ``updated_at`` is kept as it was.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from sqlalchemy import not_, or_, select, true, update
from sqlalchemy.orm import Session

from app import crypto, files
from app.db import Base, platform_session
from app.sealing import SEALED, VIA_PARENT

logger = logging.getLogger("hospital.rekey")

BATCH = 200


@dataclass
class Report:
    values: Dict[str, int] = field(default_factory=dict)
    files: Dict[str, int] = field(default_factory=dict)

    def add(self, kind: str, what: str, n: int = 1) -> None:
        bucket = self.values if kind == "values" else self.files
        bucket[what] = bucket.get(what, 0) + n


def _table(name: str):
    return Base.metadata.tables[name]


def _source(name: str, hospital_id: Optional[str] = None):
    """(select of id, hospital_id and the encrypted columns, the table)."""
    table = _table(name)
    columns = [table.c[c] for c in SEALED[name]]
    if name in VIA_PARENT:
        parent_name, fk = VIA_PARENT[name]
        parent = _table(parent_name)
        query = select(table.c.id, parent.c.hospital_id, *columns).join(parent, parent.c.id == table.c[fk])
        hospital = parent.c.hospital_id
    else:
        query = select(table.c.id, table.c.hospital_id, *columns)
        hospital = table.c.hospital_id
    if hospital_id is not None:
        query = query.where(hospital == hospital_id)
    return query, table


def _sealed_with(column, version: Optional[int] = None):
    pattern = f"{crypto.PREFIX}{version}:%" if version is not None else f"{crypto.PREFIX}%"
    return column.like(pattern)


@dataclass(frozen=True)
class Need:
    """Which values a job rewrites: as an SQL condition on a column, and as a test of a value."""

    sql: Callable
    value: Callable[[Optional[str]], bool]


PLAIN = Need(lambda column: column.is_not(None) & not_(_sealed_with(column)),
             lambda value: value is not None and not crypto.is_sealed(value))
SEALED_ANY = Need(_sealed_with, crypto.is_sealed)


def not_on(version: int) -> Need:
    prefix = f"{crypto.PREFIX}{version}:"
    return Need(lambda column: column.is_not(None) & not_(_sealed_with(column, version)),
                lambda value: value is not None and not value.startswith(prefix))


def _rewrite_values(name: str, needs: Need, convert: Callable, report: Report, label: str,
                    hospital_id: Optional[str] = None, batch: int = BATCH) -> None:
    """Rewrite, in batches, each value of table ``name`` that ``needs`` with
    ``convert(session, hospital_id, column, row_id, value)``."""
    query, table = _source(name, hospital_id)
    columns = SEALED[name]
    keep = {c.name: c for c in table.c if c.onupdate is not None}  # e.g. updated_at stays as it was
    failed: set = set()
    while True:
        with platform_session() as session:
            rows = session.execute(query.where(
                or_(*[needs.sql(table.c[c]) for c in columns]),
                table.c.id.not_in(failed) if failed else true(),
            ).order_by(table.c.id).limit(batch)).all()
            if not rows:
                return
            for row in rows:
                row_id, hospital = row[0], row[1]
                old = dict(zip(columns, row[2:]))
                new = {}
                for column, value in old.items():
                    if needs.value(value):
                        new[column] = convert(session, hospital, column, row_id, value)
                if not new:
                    failed.add(row_id)
                    continue
                guard = [table.c.id == row_id] + [table.c[c] == old[c] for c in new]
                done = session.execute(update(table).where(*guard).values(
                    **new, **{n: c for n, c in keep.items()})).rowcount
                if done:
                    report.add("values", f"{name}.{label}", len(new))
                else:
                    failed.add(row_id)  # changed meanwhile (by the app: already encrypted); next run sees it


def _sealer(session: Session, hospital_id: str, column_table: str, column: str, row_id: str, value: str,
            keys: Dict[str, crypto.DataKey]) -> str:
    plain = _plain(session, hospital_id, column_table, column, row_id, value)
    key = keys.get(hospital_id)
    if key is None:
        key = keys[hospital_id] = crypto.active_key(session, hospital_id)
    return crypto.seal(key, plain, column_table, column, row_id)


def _plain(session: Session, hospital_id: str, table: str, column: str, row_id: str, value: str) -> str:
    if not crypto.is_sealed(value):
        return value
    key = crypto.data_key(session, hospital_id, crypto.sealed_version(value))
    return crypto.unseal(key, value, table, column, row_id)


# --- files ---------------------------------------------------------------------------------------

#: Tables of files on disk (each row's id is its file's id).
FILE_TABLES = ("record_files", "onboarding_documents")


def _file_rows(hospital_id: Optional[str] = None) -> Iterator[Tuple[str, str, str, int, str]]:
    """(table, hospital_id, file id, size, sha256) of every stored file, in batches."""
    for name in FILE_TABLES:
        table = _table(name)
        after = ""
        while True:
            query = select(table.c.hospital_id, table.c.id, table.c.size, table.c.sha256).where(table.c.id > after)
            if hospital_id is not None:
                query = query.where(table.c.hospital_id == hospital_id)
            with platform_session() as session:
                rows = session.execute(query.order_by(table.c.id).limit(BATCH)).all()
            if not rows:
                break
            for hospital, file_id, size, sha256 in rows:
                yield name, hospital, file_id, size, sha256
            after = rows[-1][1]


def _rewrite_file(session: Session, hospital_id: str, file_id: str, size: int, sha256: str,
                  target: Optional[crypto.DataKey]) -> str:
    """Re-write a file encrypted with ``target`` (None: in plain text), after
    checking its plain bytes against size and sha256. Returns what was done."""
    try:
        handle, key, header = files.open_file(session, hospital_id, file_id)
    except files.FileRejected:
        return "missing"
    path = files.path_for(hospital_id, file_id)
    partial = path.with_name(path.name + ".rekey")
    try:
        with handle:
            if target is None and header is None:
                return "already plain"
            if target is not None and header is not None and key.version == target.version:
                return "already encrypted"
            digest, seen = hashlib.sha256(), 0

            def pieces():
                nonlocal seen
                for piece in files.plain_pieces(handle, key, header, file_id):
                    digest.update(piece)
                    seen += len(piece)
                    yield piece

            if target is None:
                with open(partial, "wb") as out:
                    for piece in pieces():
                        out.write(piece)
                    out.flush()
                    os.fsync(out.fileno())
            else:
                files.write_sealed(partial, pieces(), target, file_id)
        if seen != size or not hmac.compare_digest(digest.hexdigest(), sha256):
            partial.unlink(missing_ok=True)
            logger.error("file_sha256_mismatch file=%s: left as it was", file_id)
            return "sha256 mismatch (left as it was)"
        if target is not None:  # read back before replacing the original
            with open(partial, "rb") as check:
                found = crypto.read_file_header(check)
                if found is None:
                    raise crypto.CryptoError(f"File {file_id} was not written encrypted.")
                again = hashlib.sha256()
                for piece in crypto.open_chunks(check, target, found[1], file_id):
                    again.update(piece)
                if again.hexdigest() != sha256:
                    raise crypto.CryptoError(f"File {file_id} does not read back.")
        os.replace(partial, path)
        return "encrypted" if target is not None else "decrypted"
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _rewrite_files(report: Report, target_for: Callable[[Session, str], Optional[crypto.DataKey]],
                   hospital_id: Optional[str] = None) -> None:
    for _name, hospital, file_id, size, sha256 in _file_rows(hospital_id):
        with platform_session() as session:
            outcome = _rewrite_file(session, hospital, file_id, size, sha256, target_for(session, hospital))
        report.add("files", outcome)


# --- the jobs ---------------------------------------------------------------------------------------

def encrypt_existing(batch: int = BATCH) -> Report:
    """Encrypt every value and file still in plain text (idempotent)."""
    report = Report()
    for name, columns in SEALED.items():
        keys: Dict[str, crypto.DataKey] = {}
        report.add("values", f"{name}.encrypted", 0)
        _rewrite_values(name, PLAIN,
                        lambda s, h, c, i, v, name=name, keys=keys: _sealer(s, h, name, c, i, v, keys),
                        report, "encrypted", batch=batch)
    _rewrite_files(report, lambda session, hospital: crypto.active_key(session, hospital))
    return report


def decrypt_existing(batch: int = BATCH) -> Report:
    """Turn every encrypted value and file back into plain text (only to roll back)."""
    report = Report()
    for name in SEALED:
        report.add("values", f"{name}.decrypted", 0)
        _rewrite_values(name, SEALED_ANY,
                        lambda s, h, c, i, v, name=name: _plain(s, h, name, c, i, v),
                        report, "decrypted", batch=batch)
    _rewrite_files(report, lambda _session, _hospital: None)
    return report


def rotate_key(hospital_id: str, batch: int = BATCH) -> Tuple[int, Report]:
    """A new data key version for the hospital, then its values and files
    re-encrypted with it. Returns (new version, report)."""
    from app.models import Hospital

    with platform_session() as session:
        if session.get(Hospital, hospital_id) is None:
            raise LookupError(f"No hospital {hospital_id}.")
        version = crypto.add_key_version(session, hospital_id, activate=True)
    report = Report()
    for name in SEALED:
        keys: Dict[str, crypto.DataKey] = {}
        report.add("values", f"{name}.re-encrypted", 0)
        _rewrite_values(name, not_on(version),
                        lambda s, h, c, i, v, name=name, keys=keys: _sealer(s, h, name, c, i, v, keys),
                        report, "re-encrypted", hospital_id=hospital_id, batch=batch)
    _rewrite_files(report, lambda session, hospital: crypto.active_key(session, hospital), hospital_id=hospital_id)
    return version, report


def check() -> Tuple[bool, List[str]]:
    """(all encrypted with active keys, report lines)."""
    from sqlalchemy import func

    lines, clean = [], True
    with platform_session() as session:
        keys = _table("hospital_keys")
        active = dict(session.execute(select(keys.c.hospital_id, keys.c.version).where(keys.c.active.is_(True))).all())
        for name, columns in SEALED.items():
            query, table = _source(name)
            sub = query.subquery()
            for column in columns:
                plain = session.scalar(select(func.count()).select_from(sub).where(
                    sub.c[column].is_not(None), not_(_sealed_with(sub.c[column])))) or 0
                stale = 0
                for hospital, version in active.items():
                    stale += session.scalar(select(func.count()).select_from(sub).where(
                        sub.c.hospital_id == hospital, _sealed_with(sub.c[column]),
                        not_(_sealed_with(sub.c[column], version)))) or 0
                total = session.scalar(select(func.count()).select_from(sub).where(sub.c[column].is_not(None))) or 0
                lines.append(f"{name}.{column}: {total} values, {plain} plain text, {stale} on an older key")
                clean = clean and plain == 0
    counts: Dict[str, int] = {}
    for _name, hospital, file_id, _size, _sha in _file_rows():
        try:
            path = files.path_for(hospital, file_id)
            with open(path, "rb") as handle:
                found = crypto.read_file_header(handle)
            state = "plain text" if found is None else (
                "encrypted" if found[0] == active.get(hospital) else "on an older key")
        except (FileNotFoundError, files.FileRejected):
            state = "missing"
        counts[state] = counts.get(state, 0) + 1
    lines.append("files: " + (", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "none"))
    clean = clean and not counts.get("plain text")
    return clean, lines


def export_file(file_id: str, out_path: str) -> str:
    """Write a stored file's plain bytes (checked) to ``out_path`` (0600), for
    an operator: a record file or an onboarding document."""
    with platform_session() as session:
        for name in FILE_TABLES:
            table = _table(name)
            row = session.execute(select(table.c.hospital_id, table.c.size, table.c.sha256)
                                  .where(table.c.id == file_id)).first()
            if row is None:
                continue
            plain = files.open_checked(session, row[0], file_id, row[1], row[2])
            fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as out:
                for piece in plain:
                    out.write(piece)
            return name
    raise LookupError(f"No file {file_id}.")
