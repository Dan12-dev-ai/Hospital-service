"""Which columns are encrypted at rest, and the ORM boundary that does it.

The app reads and writes these attributes as plain text; only the database
holds ciphertext (app/crypto.py has the format and the keys):

* on flush (``before_flush``), each new or changed value of a column in
  :data:`SEALED` is encrypted with its hospital's active data key, bound to
  its table, column, row id and hospital; once the rows are written
  (``after_flush_postexec``) the objects get their plain text back;
* on load (``load`` and ``refresh``), each encrypted value is decrypted with
  the key version it names (a failure evicts the cached key and retries
  once). Anything that is not a well-formed encrypted value (no ``enc:v1:``
  prefix, or plain text that merely starts with it) was stored before
  encryption and is read as it is, until ``python -m app.cli
  enforce-encryption``; from then on it is refused (app/crypto.py,
  "enforcement").
* if a flush fails (and its transaction or savepoint is rolled back), the
  objects get their plain text back and the next flush encrypts again, with
  the key that is active then: never with a key from a rolled-back savepoint.

Only the ORM goes through here: a Core statement (``select(Model.column)``,
``update(...).values(column=...)``) on these columns would see or write
ciphertext, so the app does not use any (the CLI jobs in app/rekey.py work on
ciphertext on purpose).

What stays plain text, and why (README, "Encryption at rest"): patients'
names, phone numbers and other identifiers (searched by staff), categories,
dates and statuses (filtered and sorted), a retraction's reason, and
pharmacies' dispense amounts.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session, attributes
from sqlalchemy.orm.util import identity_key

from app import crypto
from app.db import Base, new_id

#: table -> its encrypted columns (each also the attribute's name).
SEALED: Dict[str, Tuple[str, ...]] = {
    "clinical_records": ("title", "details"),
    "visits": ("follow_up_note",),
    "patients": ("diagnosis",),
    "patient_alerts": ("label",),
    "bookings": ("notes",),
    "record_files": ("filename",),
    "shared_records": ("title", "details", "files"),
    "import_batches": ("plan",),
    # Migration 0009: the integration API.
    "integration_clients": ("webhook_secret",),
    "integration_idempotency": ("response",),
    "webhook_deliveries": ("body",),
    # Migration 0010: authenticator secrets.
    "staff_users": ("totp_secret", "totp_pending_secret"),
}

#: Tables whose hospital is their parent row's: table -> (parent table, foreign key column).
VIA_PARENT: Dict[str, Tuple[str, str]] = {"shared_records": ("record_shares", "share_id")}

_PLAIN = "sealing.plain"


def _model(table: str):
    for mapper in Base.registry.mappers:
        if mapper.local_table is not None and mapper.local_table.name == table:
            return mapper.class_
    raise KeyError(table)


def _parent_hospital(session: Session, parent: str, parent_id: Optional[str]) -> str:
    model = _model(parent)
    found = session.identity_map.get(identity_key(model, parent_id))
    if found is None:
        found = next((o for o in session.new if isinstance(o, model) and o.id == parent_id), None)
    if found is not None:
        return found.hospital_id
    table = Base.metadata.tables[parent]
    hospital_id = session.connection().execute(select(table.c.hospital_id).where(table.c.id == parent_id)).scalar()
    if hospital_id is None:
        raise crypto.CryptoError(f"{parent} row {parent_id} is not visible: its children cannot be encrypted.")
    return hospital_id


def hospital_of(session: Session, obj) -> str:
    table = obj.__table__.name
    if table in VIA_PARENT:
        parent, fk = VIA_PARENT[table]
        return _parent_hospital(session, parent, getattr(obj, fk))
    return obj.hospital_id


@event.listens_for(Session, "before_flush")
def _seal_on_flush(session: Session, _flush_context, _instances) -> None:
    keys: Dict[str, crypto.DataKey] = {}
    plain = session.info.setdefault(_PLAIN, [])
    for obj in list(session.new) + list(session.dirty):
        table = getattr(obj, "__table__", None)
        columns = SEALED.get(table.name) if table is not None else None
        if not columns:
            continue
        state = inspect(obj)
        new = state.pending or state.transient
        changed = []
        for column in columns:
            if new:
                value = state.dict.get(column)
                default = table.c[column].default
                if value is None and default is not None and default.is_scalar:
                    value = default.arg
            else:
                added = state.attrs[column].history.added
                value = added[0] if added else None
            if value is None:
                continue
            if not isinstance(value, str):
                raise TypeError(f"{table.name}.{column} holds text only")
            changed.append((column, value))
        if not changed:
            continue
        if obj.id is None:
            obj.id = new_id()  # the row id is part of the associated data
        hospital_id = hospital_of(session, obj)
        key = keys.get(hospital_id)
        if key is None:
            key = keys[hospital_id] = crypto.active_key(session, hospital_id)
        for column, value in changed:
            setattr(obj, column, crypto.seal(key, value, table.name, column, obj.id))
            plain.append((obj, column, value))


@event.listens_for(Session, "after_flush_postexec")
def _after_flush(session: Session, _flush_context) -> None:
    """Written: the objects hold plain text again (not a change to save)."""
    for obj, column, value in session.info.pop(_PLAIN, []):
        attributes.set_committed_value(obj, column, value)


def _undo_failed_flush(session: Session) -> None:
    """A flush that encrypted values failed: forget that they were encrypted.
    A new object gets its plain text back (the next flush encrypts it again,
    with the key active then); a stored one is reloaded from the database."""
    for obj, column, value in session.info.pop(_PLAIN, []):
        state = inspect(obj)
        if state.persistent and state.session_id == session.hash_key:
            session.expire(obj, [column])
        else:
            obj.__dict__[column] = value


@event.listens_for(Session, "after_soft_rollback")
def _after_rollback(session: Session, _previous_transaction) -> None:
    _undo_failed_flush(session)


@event.listens_for(Session, "after_transaction_end")
def _after_transaction_end(session: Session, _transaction) -> None:
    # A successful flush has given its values back already; anything left is
    # from a flush that failed (in a transaction or a savepoint now ended).
    if session.info.get(_PLAIN):
        _undo_failed_flush(session)


def where(obj, column: str) -> str:
    return f"{obj.__table__.name}.{column} of row {obj.id}"


def unseal_value(session: Session, obj, column: str, value):
    if value is None:
        return None
    if not crypto.is_sealed(value):
        if crypto.enforced(session):
            raise crypto.refuse_plaintext(where(obj, column))
        return value  # plain text stored before encryption
    return crypto.open_value(session, hospital_of(session, obj), value, obj.__table__.name, column, obj.id)


def _unseal(obj, session: Optional[Session], only=None) -> None:
    columns = SEALED[obj.__table__.name]
    for column in columns:
        if only is not None and column not in only:
            continue
        value = obj.__dict__.get(column)
        if value is None:
            continue
        if session is None:
            raise crypto.CryptoError(f"{where(obj, column)} cannot be read outside a session.")
        # The loaded value itself: not a change to save.
        obj.__dict__[column] = unseal_value(session, obj, column, value)


def _on_load(obj, context) -> None:
    _unseal(obj, context.session)


def _on_refresh(obj, context, attrs) -> None:
    _unseal(obj, context.session, attrs)


def register() -> None:
    for table in SEALED:
        model = _model(table)
        if not event.contains(model, "load", _on_load):
            event.listen(model, "load", _on_load)
            event.listen(model, "refresh", _on_refresh)


register()
