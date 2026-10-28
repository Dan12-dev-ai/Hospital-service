"""Operator jobs for encryption at rest (``python -m app.cli ...``), run for
Endod across hospitals (platform scope), in batches, each its own transaction:

* :func:`encrypt_existing` encrypts what was stored in plain text before
  encryption (values and files). Safe to stop and run again.
* :func:`check` counts what is still plain text (and what is encrypted with
  a key version that is no longer active).
* :func:`enforce` records that plaintext is refused from now on (only after
  a clean check); :func:`decrypt_existing` lifts it first.
* :func:`rotate_key` gives a hospital a new data key version and re-encrypts
  its values and files with it. Old versions are kept (inactive), never
  purged: a file whose upload started before the rotation is stored with the
  key active when it started and stays readable (``rotate-key --resume``
  moves such stragglers to the active version), and so do backups.
* :func:`decrypt_existing` turns everything back into plain text: only to
  roll back migration 0008 (README, "Encryption at rest").

"Plain text" is anything that is not a well-formed encrypted value
(:func:`app.crypto.parse_sealed`), so a legacy value that merely starts with
``enc:v1:`` is found and encrypted too. Rows are read in id order (keyset
pages) and changed with Core statements on the ciphertext, each guarded by
the value it read (``WHERE column = <old value>``): a row the app changed
meanwhile is left alone (the app wrote it encrypted already).
``updated_at`` is kept as it was.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from sqlalchemy import or_, select, update
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


def _rows(name: str, hospital_id: Optional[str] = None, batch: int = BATCH):
    """Pages of (id, hospital_id, *encrypted values) with any value set, in id order."""
    query, table = _source(name, hospital_id)
    query = query.where(or_(*[table.c[c].is_not(None) for c in SEALED[name]]))
    after = ""
    while True:
        with platform_session() as session:
            rows = session.execute(query.where(table.c.id > after).order_by(table.c.id).limit(batch)).all()
        if not rows:
            return
        yield rows
        after = rows[-1][0]


def is_plain(value: Optional[str]) -> bool:
    return value is not None and not crypto.is_sealed(value)


def not_on(version: int) -> Callable[[Optional[str]], bool]:
    def needs(value: Optional[str]) -> bool:
        parsed = crypto.parse_sealed(value)
        return value is not None and (parsed is None or parsed[0] != version)

    return needs


def _rewrite_values(name: str, needs: Callable[[Optional[str]], bool], convert: Callable, report: Report, label: str,
                    hospital_id: Optional[str] = None, batch: int = BATCH) -> None:
    """Rewrite each value of table ``name`` that ``needs`` it with
    ``convert(session, hospital_id, column, row_id, value)``."""
    table = _table(name)
    columns = SEALED[name]
    keep = {c.name: c for c in table.c if c.onupdate is not None}  # e.g. updated_at stays as it was
    for page in _rows(name, hospital_id, batch):
        todo = [row for row in page if any(needs(v) for v in row[2:])]
        if not todo:
            continue
        with platform_session() as session:
            for row in todo:
                row_id, hospital = row[0], row[1]
                old = dict(zip(columns, row[2:]))
                new = {c: convert(session, hospital, c, row_id, v) for c, v in old.items() if needs(v)}
                guard = [table.c.id == row_id] + [table.c[c] == old[c] for c in new]
                done = session.execute(update(table).where(*guard).values(
                    **new, **{n: c for n, c in keep.items()})).rowcount
                if done:
                    report.add("values", f"{name}.{label}", len(new))
                # else: changed meanwhile by the app, which wrote it encrypted.


def _sealer(session: Session, hospital_id: str, table: str, column: str, row_id: str, value: str,
            keys: Dict[str, crypto.DataKey]) -> str:
    plain = _plain(session, hospital_id, table, column, row_id, value)
    key = keys.get(hospital_id)
    if key is None:
        key = keys[hospital_id] = crypto.active_key(session, hospital_id)
    return crypto.seal(key, plain, table, column, row_id)


def _plain(session: Session, hospital_id: str, table: str, column: str, row_id: str, value: str) -> str:
    if not crypto.is_sealed(value):
        return value
    return crypto.open_value(session, hospital_id, value, table, column, row_id)


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
    """Re-write a file encrypted with ``target`` (None: in plain text). It is
    read and checked against size and sha256 first (with the key retry of
    :func:`app.files.open_checked`), and the new file is read back before it
    replaces the old one. Returns what was done."""
    try:
        plain = files.open_checked(session, hospital_id, file_id, size, sha256)
    except files.FileRejected:
        return "missing"
    except files.FileDamaged:
        logger.error("file_sha256_mismatch file=%s: left as it was", file_id)
        return "sha256 mismatch (left as it was)"
    if (target is None and plain.version is None) or (target is not None and plain.version == target.version):
        plain.close()
        return "already plain" if target is None else "already encrypted"
    path = files.path_for(hospital_id, file_id)
    partial = path.with_name(path.name + ".rekey")
    try:
        if target is None:
            with open(partial, "wb") as out:
                for piece in plain:
                    out.write(piece)
                out.flush()
                os.fsync(out.fileno())
        else:
            files.write_sealed(partial, plain, target, file_id)
        with open(partial, "rb") as check_handle:  # read back before replacing the original
            found = crypto.read_file_header(check_handle)
            if (found is None) != (target is None):
                raise crypto.CryptoError(f"File {file_id} was not written as intended.")
            again = hashlib.sha256()
            pieces = files.plain_pieces(check_handle, target, found[1] if found else None, file_id)
            for piece in pieces:
                again.update(piece)
            if not hmac.compare_digest(again.hexdigest(), sha256):
                raise crypto.CryptoError(f"File {file_id} does not read back.")
        os.replace(partial, path)
        return "encrypted" if target is not None else "decrypted"
    except BaseException:
        plain.close()
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
    for name in SEALED:
        keys: Dict[str, crypto.DataKey] = {}
        report.add("values", f"{name}.encrypted", 0)
        _rewrite_values(name, is_plain,
                        lambda s, h, c, i, v, name=name, keys=keys: _sealer(s, h, name, c, i, v, keys),
                        report, "encrypted", batch=batch)
    _rewrite_files(report, lambda session, hospital: crypto.active_key(session, hospital))
    return report


def is_enforced() -> bool:
    with platform_session() as session:
        crypto.clear_enforced_cache()
        return crypto.enforced(session)


def enforce() -> Tuple[bool, List[str]]:
    """Refuse plaintext from now on, if (and only if) nothing is left in plain
    text. Returns (enforced, the check's lines)."""
    clean, lines = check()
    if clean:
        with platform_session() as session:
            crypto.set_enforced(session, True)
    return clean, lines


def decrypt_existing(batch: int = BATCH) -> Report:
    """Turn every encrypted value and file back into plain text (only to roll
    back). Lifts enforcement first, or the app would refuse what this writes."""
    with platform_session() as session:
        crypto.set_enforced(session, False)
    report = Report()
    for name in SEALED:
        report.add("values", f"{name}.decrypted", 0)
        _rewrite_values(name, crypto.is_sealed,
                        lambda s, h, c, i, v, name=name: _plain(s, h, name, c, i, v),
                        report, "decrypted", batch=batch)
    _rewrite_files(report, lambda _session, _hospital: None)
    return report


def rotate_key(hospital_id: str, batch: int = BATCH, new_key: bool = True) -> Tuple[int, Report]:
    """A new data key version for the hospital (``new_key``; without it, the
    active version stays), then its values and files on any other version, or
    in plain text, re-encrypted with the active one. Returns (active version, report)."""
    from app.models import Hospital

    with platform_session() as session:
        if session.get(Hospital, hospital_id) is None:
            raise LookupError(f"No hospital {hospital_id}.")
        if new_key:
            version = crypto.add_key_version(session, hospital_id, activate=True)
        else:
            version = crypto.active_key(session, hospital_id).version
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
    """(nothing left in plain text, report lines). Every value is looked at
    (well-formedness is checked here, not with SQL LIKE)."""
    lines, clean = [], True
    with platform_session() as session:
        keys = _table("hospital_keys")
        active = dict(session.execute(select(keys.c.hospital_id, keys.c.version).where(keys.c.active.is_(True))).all())
    for name, columns in SEALED.items():
        counts = {c: [0, 0, 0] for c in columns}  # values, plain text, on an older key
        for page in _rows(name):
            for row in page:
                hospital = row[1]
                for column, value in zip(columns, row[2:]):
                    if value is None:
                        continue
                    tally = counts[column]
                    tally[0] += 1
                    parsed = crypto.parse_sealed(value)
                    if parsed is None:
                        tally[1] += 1
                    elif parsed[0] != active.get(hospital):
                        tally[2] += 1
        for column, (total, plain, stale) in counts.items():
            lines.append(f"{name}.{column}: {total} values, {plain} plain text, {stale} on an older key")
            clean = clean and plain == 0
    states: Dict[str, int] = {}
    for _name, hospital, file_id, _size, _sha in _file_rows():
        try:
            with open(files.path_for(hospital, file_id), "rb") as handle:
                found = crypto.read_file_header(handle)
            state = "plain text" if found is None else (
                "encrypted" if found[0] == active.get(hospital) else "on an older key")
        except (FileNotFoundError, files.FileRejected):
            state = "missing"
        states[state] = states.get(state, 0) + 1
    lines.append("files: " + (", ".join(f"{n} {s}" for s, n in sorted(states.items())) or "none"))
    clean = clean and not states.get("plain text")
    lines.append(f"enforced: {'yes' if is_enforced() else 'no'}")
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
