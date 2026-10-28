"""Encryption of health data at rest (app/crypto.py, app/sealing.py, app/rekey.py)."""

import asyncio
import hashlib
import io
import json
import os
from datetime import timedelta

import pytest
from sqlalchemy import select, text, update

from conftest import make_hospital
from history_support import (  # noqa: F401  (fixtures)
    PDF, PNG, bus, events, link_directly, platform_key, register, staff, today, upload,
)

from app import crypto, eventbus, files, rekey
from app.db import Base, platform_session, session_scope, utcnow
from app.models import ClinicalRecord, OutboxEvent, RecordFile

MARK = "Quokkafever"  # in every clinical field below; must never reach the database or disk in plain text
DIAGNOSIS = {"category": "diagnosis", "title": f"{MARK} suspected", "details": {
    "condition": f"{MARK} infection", "code": "B50.9", "status": "active", "notes": f"{MARK} notes"}}


@pytest.fixture
def doctor(client, hospital):
    return staff(client, hospital, "doctor")


@pytest.fixture
def patient(client, hospital):
    return register(client, staff(client, hospital, "reception"))


def add(client, headers, patient_id, body=DIAGNOSIS):
    resp = client.post(f"/patients/{patient_id}/records", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def raw(sql, **params):
    """Rows as stored (no ORM, so no decryption), across hospitals."""
    with platform_session() as session:
        return session.execute(text(sql), params).all()


def key_for(hospital_id):
    with platform_session() as session:
        return crypto.active_key(session, hospital_id)


# --- values ---------------------------------------------------------------------------------------

def test_values_round_trip_and_are_bound_to_their_place(db):
    key = crypto.DataKey("h1", 1, os.urandom(32))
    for plain in ("", "Malaria", "ወባ በሽታ " * 200, json.dumps({"a": [1, 2]})):
        sealed = crypto.seal(key, plain, "clinical_records", "title", "r1")
        assert sealed.startswith("enc:v1:1:") and (not plain or plain not in sealed)
        assert crypto.unseal(key, sealed, "clinical_records", "title", "r1") == plain
    sealed = crypto.seal(key, "Malaria", "clinical_records", "title", "r1")
    assert sealed != crypto.seal(key, "Malaria", "clinical_records", "title", "r1")  # a fresh nonce each time
    for table, column, row in (("clinical_records", "title", "r2"),     # another row
                               ("clinical_records", "details", "r1"),   # another column
                               ("shared_records", "title", "r1")):      # another table
        with pytest.raises(crypto.CryptoError):
            crypto.unseal(key, sealed, table, column, row)
    with pytest.raises(crypto.CryptoError):  # another hospital (even with the same key bytes)
        crypto.unseal(crypto.DataKey("h2", 1, key.secret), sealed, "clinical_records", "title", "r1")
    with pytest.raises(crypto.CryptoError):  # a wrong key
        crypto.unseal(crypto.DataKey("h1", 1, os.urandom(32)), sealed, "clinical_records", "title", "r1")
    with pytest.raises(crypto.CryptoError):  # tampered
        crypto.unseal(key, sealed[:-6] + ("A" if sealed[-6] != "A" else "B") + sealed[-5:],
                      "clinical_records", "title", "r1")
    assert "secret" not in repr(key) and repr(key.secret) not in repr(key)


def test_no_plain_text_reaches_the_database_or_the_disk(client, hospital, doctor, patient):
    nurse = staff(client, hospital, "nurse")
    file_id = upload(client, doctor, patient["id"], PDF + MARK.encode(), f"{MARK}.pdf").json()["id"]
    record = add(client, doctor, patient["id"], {**DIAGNOSIS, "file_ids": [file_id]})
    assert record["title"] == DIAGNOSIS["title"] and record["details"]["notes"] == f"{MARK} notes"
    assert record["files"][0]["filename"] == f"{MARK}.pdf"
    assert client.patch(f"/patients/{patient['id']}", headers=doctor,
                        json={"diagnosis": f"{MARK} (working)"}).status_code == 200
    assert client.post(f"/patients/{patient['id']}/alerts", headers=nurse,
                       json={"kind": "allergy", "label": f"{MARK} allergy"}).status_code == 201
    visit = client.post(f"/patients/{patient['id']}/visits", headers=doctor, json={
        "follow_up_on": (today() + timedelta(days=7)).isoformat(), "follow_up_note": f"{MARK} review"})
    assert visit.status_code == 201 and visit.json()["follow_up_note"] == f"{MARK} review"

    # Every text column of every table, as stored.
    for name, table in Base.metadata.tables.items():
        for column in table.c:
            if column.type.python_type is not str:
                continue
            for (value,) in raw(f"SELECT {column.name} FROM {name}"):
                assert value is None or MARK not in value, f"{name}.{column.name} holds plain text"
    [(title, details)] = raw("SELECT title, details FROM clinical_records")
    assert title.startswith("enc:v1:1:") and details.startswith("enc:v1:1:")
    for path in (files.root()).rglob("*"):
        if path.is_file():
            assert MARK.encode() not in path.read_bytes() and path.read_bytes().startswith(crypto.FILE_MAGIC)

    # ...and the API reads it all back.
    got = client.get(f"/patients/{patient['id']}/records", headers=doctor).json()["items"][0]
    assert got["title"] == DIAGNOSIS["title"] and got["details"]["condition"] == f"{MARK} infection"
    shown = client.get(f"/patients/{patient['id']}", headers=doctor).json()
    assert shown["diagnosis"] == f"{MARK} (working)" and shown["alerts"][0]["label"] == f"{MARK} allergy"
    download = client.get(f"/records/{record['id']}/files/{file_id}", headers=doctor)
    assert download.status_code == 200 and download.content == PDF + MARK.encode()
    assert download.headers["x-sha256"] == hashlib.sha256(PDF + MARK.encode()).hexdigest()


def test_ciphertext_moved_to_another_row_does_not_decrypt(client, hospital, doctor, patient):
    first = add(client, doctor, patient["id"])
    second = add(client, doctor, patient["id"], {**DIAGNOSIS, "title": "Second"})
    with platform_session() as session:
        stored = session.execute(select(ClinicalRecord.__table__.c.details)
                                 .where(ClinicalRecord.__table__.c.id == first["id"])).scalar()
        session.execute(update(ClinicalRecord.__table__).where(ClinicalRecord.__table__.c.id == second["id"])
                        .values(details=stored))
    with pytest.raises(crypto.CryptoError, match="does not decrypt"):
        with session_scope(hospital) as session:
            session.get(ClinicalRecord, second["id"])
    with session_scope(hospital) as session:  # the first is untouched
        assert json.loads(session.get(ClinicalRecord, first["id"]).details)["notes"] == f"{MARK} notes"


def test_ciphertext_moved_to_another_hospital_does_not_decrypt(client, hospital, doctor, patient):
    record = add(client, doctor, patient["id"])
    other = make_hospital(code="TKH", name="Tikur Anbessa")
    other_doctor = staff(client, other, "doctor", name="other-doctor")
    other_patient = register(client, staff(client, other, "reception", name="other-desk"))
    target = add(client, other_doctor, other_patient["id"], {**DIAGNOSIS, "title": "Other"})
    table = ClinicalRecord.__table__
    with platform_session() as session:
        title = session.execute(select(table.c.title).where(table.c.id == record["id"])).scalar()
        # Even with the same row id the hospital's key and the associated data differ.
        session.execute(update(table).where(table.c.id == target["id"]).values(title=title))
    with pytest.raises(crypto.CryptoError):
        with session_scope(other) as session:
            session.get(ClinicalRecord, target["id"])


def test_a_wrong_master_key_reads_nothing(client, hospital, doctor, patient, tmp_path, monkeypatch):
    add(client, doctor, patient["id"])
    wrong = tmp_path / "wrong.key"
    wrong.write_bytes(os.urandom(32))
    monkeypatch.setenv("HOSPITAL_MASTER_KEY_FILE", str(wrong))
    crypto.clear_cache()
    with pytest.raises(crypto.CryptoError, match="does not unwrap"):
        client.get(f"/patients/{patient['id']}/records", headers=doctor)


def test_the_master_key_is_required_outside_development(db, tmp_path, monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("HOSPITAL_ENVIRONMENT", "production")
    monkeypatch.delenv("HOSPITAL_MASTER_KEY_FILE")
    crypto.clear_cache()
    with pytest.raises(crypto.CryptoError, match="HOSPITAL_MASTER_KEY_FILE is not set"):
        create_app()
    short = tmp_path / "short.key"
    short.write_bytes(os.urandom(31))
    monkeypatch.setenv("HOSPITAL_MASTER_KEY_FILE", str(short))
    with pytest.raises(crypto.CryptoError, match="32 random bytes"):
        create_app()
    missing = tmp_path / "missing.key"
    monkeypatch.setenv("HOSPITAL_MASTER_KEY_FILE", str(missing))
    with pytest.raises(crypto.CryptoError, match="cannot be read"):
        create_app()
    hexed = tmp_path / "hex.key"
    kek = os.urandom(32)
    hexed.write_text(kek.hex() + "\n")
    monkeypatch.setenv("HOSPITAL_MASTER_KEY_FILE", str(hexed))
    create_app()  # 64 hex characters (openssl rand -hex 32) are accepted too
    assert crypto.check_master_key() == crypto.fingerprint(kek) and kek.hex()[:16] not in crypto.fingerprint(kek)


@pytest.mark.parametrize("environment", [None, "staging", "dev", ""])
def test_without_a_key_only_an_explicit_development_or_test_environment_starts(db, monkeypatch, environment):
    from app.main import create_app

    monkeypatch.delenv("HOSPITAL_MASTER_KEY_FILE")
    if environment is None:
        monkeypatch.delenv("HOSPITAL_ENVIRONMENT")  # the default is development, but not said explicitly
    else:
        monkeypatch.setenv("HOSPITAL_ENVIRONMENT", environment)
    crypto.clear_cache()
    with pytest.raises(crypto.CryptoError, match="HOSPITAL_MASTER_KEY_FILE is not set"):
        create_app()
    for explicit in ("development", "test", " Test "):
        monkeypatch.setenv("HOSPITAL_ENVIRONMENT", explicit)
        create_app()
        assert crypto.master_key() == crypto._DEVELOPMENT_KEY


def test_each_hospital_gets_its_own_key_once(db):
    first, second = make_hospital(), make_hospital(code="TKH", name="Tikur Anbessa")
    a, b = key_for(first), key_for(second)
    assert a.secret != b.secret and a.version == b.version == 1
    crypto.clear_cache()
    assert key_for(first).secret == a.secret  # stored wrapped, and unwrapped again
    rows = raw("SELECT hospital_id, version, wrapped_key, active FROM hospital_keys ORDER BY hospital_id")
    assert len(rows) == 2 and all(r[3] for r in rows)
    assert all(a.secret.hex() not in r[2] and a.secret not in r[2].encode() for r in rows)


# --- files ------------------------------------------------------------------------------------------

def _seal_bytes(key, file_id, data, piece=7919):
    sealer = crypto.FileSealer(key, file_id)
    out = [sealer.header()]
    for start in range(0, len(data), piece):
        out.append(sealer.update(data[start:start + piece]))
    out.append(sealer.finish())
    return b"".join(out)


def _open_bytes(key, file_id, blob):
    handle = io.BytesIO(blob)
    version, header = crypto.read_file_header(handle)
    assert version == key.version
    return b"".join(crypto.open_chunks(handle, key, header, file_id))


@pytest.mark.parametrize("size", [0, 1, crypto.CHUNK - 1, crypto.CHUNK, crypto.CHUNK + 1, 2 * crypto.CHUNK,
                                  5 * crypto.CHUNK + 123, 3 * 1024 * 1024 + 17])
def test_files_round_trip_in_chunks(size):
    key = crypto.DataKey("a" * 32, 3, os.urandom(32))
    data = os.urandom(size)
    blob = _seal_bytes(key, "f" * 32, data)
    chunks = max(1, -(-size // crypto.CHUNK))
    assert len(blob) == crypto.FILE_HEADER_BYTES + size + chunks * (crypto.NONCE_BYTES + crypto.TAG_BYTES)
    assert _open_bytes(key, "f" * 32, blob) == data


def test_a_file_cut_short_reordered_moved_or_under_another_key_does_not_decrypt():
    key = crypto.DataKey("a" * 32, 1, os.urandom(32))
    data = os.urandom(3 * crypto.CHUNK + 10)
    blob = _seal_bytes(key, "f" * 32, data)
    record = crypto.NONCE_BYTES + crypto.CHUNK + crypto.TAG_BYTES
    head, body = blob[:crypto.FILE_HEADER_BYTES], blob[crypto.FILE_HEADER_BYTES:]
    chunks = [body[i:i + record] for i in range(0, len(body), record)]
    damaged = {
        "cut at a chunk boundary": head + b"".join(chunks[:2]),
        "cut inside a chunk": blob[:-5],
        "two chunks swapped": head + chunks[1] + chunks[0] + b"".join(chunks[2:]),
        "one byte changed": blob[:-1] + bytes([blob[-1] ^ 1]),
        "nothing after the header": head,
    }
    for what, broken in damaged.items():
        with pytest.raises(crypto.CryptoError):
            _open_bytes(key, "f" * 32, broken)
            pytest.fail(what)
    with pytest.raises(crypto.CryptoError):  # another file's id
        _open_bytes(key, "e" * 32, blob)
    with pytest.raises(crypto.CryptoError):  # another hospital
        _open_bytes(crypto.DataKey("b" * 32, 1, key.secret), "f" * 32, blob)
    with pytest.raises(crypto.CryptoError):  # a wrong key
        _open_bytes(crypto.DataKey("a" * 32, 1, os.urandom(32)), "f" * 32, blob)


def test_uploads_are_encrypted_as_they_stream_and_checked_when_read(db, hospital):
    key = key_for(hospital)
    data = PDF + os.urandom(6 * 1024 * 1024 + 3)

    async def pieces():
        for start in range(0, len(data), 10_007):
            yield data[start:start + 10_007]

    file_id = "c" * 32
    size, sha256, content_type = asyncio.run(files.store_stream(pieces(), hospital, file_id, key))
    assert (size, sha256, content_type) == (len(data), hashlib.sha256(data).hexdigest(), "application/pdf")
    stored = files.path_for(hospital, file_id).read_bytes()
    assert stored.startswith(crypto.FILE_MAGIC) and data[:4096] not in stored
    with platform_session() as session:
        assert b"".join(files.open_checked(session, hospital, file_id, size, sha256)) == data
        with pytest.raises(files.FileDamaged):  # the stored sha256 is checked
            files.open_checked(session, hospital, file_id, size, hashlib.sha256(b"other").hexdigest())
        with pytest.raises(files.FileDamaged):
            files.open_checked(session, hospital, file_id, size - 1, sha256)

    async def empty():
        if False:
            yield b""

    with pytest.raises(files.FileRejected, match="empty"):
        asyncio.run(files.store_stream(empty(), hospital, "d" * 32, key))
    assert not files.path_for(hospital, "d" * 32).exists()
    assert not any(p.name.endswith(".part") for p in files.root().rglob("*"))
    with pytest.raises(crypto.CryptoError):  # never with another hospital's key
        files.store_bytes(PDF, hospital, "e" * 32, crypto.DataKey("b" * 32, 1, key.secret))


def test_a_replaced_file_fails_its_sha256_and_nothing_is_sent(client, hospital, doctor, patient):
    file_id = upload(client, doctor, patient["id"], PNG, "scan.png").json()["id"]
    record = add(client, doctor, patient["id"], {**DIAGNOSIS, "file_ids": [file_id]})
    path = files.path_for(hospital, file_id)
    files.write_sealed(path, [PNG + b"forged"], key_for(hospital), file_id)  # valid encryption, other content
    with pytest.raises(files.FileDamaged):
        client.get(f"/records/{record['id']}/files/{file_id}", headers=doctor)


# --- the jobs: encrypt-existing, check, rotate-key, decrypt-existing --------------------------------

def _stored_state():
    values = {}
    for table, columns in rekey.SEALED.items():
        for column in columns:
            values[(table, column)] = [v for (v,) in raw(f"SELECT {column} FROM {table}") if v is not None]
    return values


def _seed(client, hospital, doctor, patient):
    file_id = upload(client, doctor, patient["id"], PNG, f"{MARK}.png").json()["id"]
    record = add(client, doctor, patient["id"], {**DIAGNOSIS, "file_ids": [file_id]})
    client.post(f"/patients/{patient['id']}/alerts", headers=staff(client, hospital, "nurse"),
                json={"kind": "allergy", "label": "Penicillin"})
    return record, file_id


def _reads_back(client, doctor, patient, record, file_id):
    got = client.get(f"/patients/{patient['id']}/records", headers=doctor).json()["items"][0]
    assert got["title"] == DIAGNOSIS["title"] and got["details"]["notes"] == f"{MARK} notes"
    download = client.get(f"/records/{record['id']}/files/{file_id}", headers=doctor)
    assert download.status_code == 200 and download.content == PNG


def test_encrypt_existing_encrypts_plain_rows_and_files_and_can_run_again(client, hospital, doctor, patient):
    record, file_id = _seed(client, hospital, doctor, patient)
    # As before encryption: everything in plain text (decrypt-existing, the rollback, gets there).
    rekey.decrypt_existing()
    state = _stored_state()
    assert state[("clinical_records", "title")] == [DIAGNOSIS["title"]]
    assert all(not crypto.is_sealed(v) for vs in state.values() for v in vs)
    assert files.path_for(hospital, file_id).read_bytes() == PNG
    clean, lines = rekey.check()
    assert not clean and "clinical_records.title: 1 values, 1 plain text, 0 on an older key" in lines
    assert "files: 1 plain text" in lines
    _reads_back(client, doctor, patient, record, file_id)  # plain values and files are still read

    report = rekey.encrypt_existing(batch=1)
    assert report.values["clinical_records.encrypted"] == 2 and report.files == {"encrypted": 1}
    state = _stored_state()
    assert all(crypto.is_sealed(v) for vs in state.values() for v in vs)
    assert files.path_for(hospital, file_id).read_bytes().startswith(crypto.FILE_MAGIC)
    assert rekey.check()[0] is True
    _reads_back(client, doctor, patient, record, file_id)

    again = rekey.encrypt_existing()
    assert set(again.values.values()) == {0} and again.files == {"already encrypted": 1}
    assert _stored_state() == state  # nothing rewritten


def test_encrypt_existing_keeps_updated_at_and_leaves_rows_the_app_changed(client, hospital, doctor, patient):
    record, _file_id = _seed(client, hospital, doctor, patient)
    rekey.decrypt_existing()
    before = raw("SELECT updated_at FROM clinical_records")
    rekey.encrypt_existing()
    assert raw("SELECT updated_at FROM clinical_records") == before


def test_a_damaged_plain_file_is_left_alone(client, hospital, doctor, patient):
    _record, file_id = _seed(client, hospital, doctor, patient)
    rekey.decrypt_existing()
    files.path_for(hospital, file_id).write_bytes(PNG + b"changed on disk")
    report = rekey.encrypt_existing()
    assert report.files == {"sha256 mismatch (left as it was)": 1}
    assert files.path_for(hospital, file_id).read_bytes() == PNG + b"changed on disk"


def test_rotate_key_re_encrypts_one_hospital(client, hospital, doctor, patient):
    record, file_id = _seed(client, hospital, doctor, patient)
    other = make_hospital(code="TKH", name="Tikur Anbessa")
    other_patient = register(client, staff(client, other, "reception", name="other-desk"))
    other_record = add(client, staff(client, other, "doctor", name="other-doctor"), other_patient["id"])
    other_title = raw("SELECT title FROM clinical_records WHERE id = :id", id=other_record["id"])[0][0]

    version, report = rekey.rotate_key(hospital)
    assert version == 2 and report.values["clinical_records.re-encrypted"] == 2 and report.files == {"encrypted": 1}
    assert raw("SELECT version, active FROM hospital_keys WHERE hospital_id = :h ORDER BY version",
               h=hospital) == [(1, False), (2, True)]
    titles = dict(raw("SELECT id, title FROM clinical_records"))
    assert titles[record["id"]].startswith("enc:v1:2:")
    assert titles[other_record["id"]] == other_title  # another hospital: untouched
    with open(files.path_for(hospital, file_id), "rb") as handle:
        assert crypto.read_file_header(handle)[0] == 2
    crypto.clear_cache()
    _reads_back(client, doctor, patient, record, file_id)
    assert rekey.check()[0] is True
    # New writes use the new version; a second rotation works the same way.
    assert add(client, doctor, patient["id"])["title"] == DIAGNOSIS["title"]
    assert all(t.startswith("enc:v1:2:") for (t,) in raw("SELECT title FROM clinical_records WHERE hospital_id = :h",
                                                          h=hospital))
    assert rekey.rotate_key(hospital)[0] == 3
    _reads_back(client, doctor, patient, record, file_id)


def test_the_cli_commands(client, hospital, doctor, patient, capsys, tmp_path):
    from app import cli

    _record, file_id = _seed(client, hospital, doctor, patient)
    assert cli.main(["check-encryption"]) == 0
    with pytest.raises(SystemExit):
        cli.main(["decrypt-existing"])
    assert cli.main(["decrypt-existing", "--yes"]) == 0
    assert cli.main(["check-encryption"]) == 1
    assert cli.main(["encrypt-existing"]) == 0
    assert cli.main(["rotate-key", "--hospital", "sph"]) == 0
    assert "data key version 2 is active" in capsys.readouterr().out
    out = tmp_path / "exported.png"
    assert cli.main(["export-file", "--file", file_id, "--out", str(out)]) == 0
    assert out.read_bytes() == PNG


def test_migration_0008_refuses_to_downgrade_over_ciphertext(tmp_path, monkeypatch):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    from app import db as dbmod
    from app.db import get_engine

    monkeypatch.setenv("HOSPITAL_DATABASE_URL", f"sqlite:///{tmp_path / 'downgrade.db'}")
    dbmod.reset_engine()
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "head")
    with get_engine().begin() as connection:
        connection.execute(text("INSERT INTO hospitals (id, code, name, timezone, created_at) "
                                "VALUES ('h1', 'SPH', 'St. Paul', 'Africa/Addis_Ababa', '2026-01-01 00:00:00')"))
        connection.execute(text(
            "INSERT INTO patients (id, hospital_id, mrn, full_name, sex, dob_estimated, payer, status, diagnosis, "
            "created_at, updated_at) VALUES ('p1', 'h1', 'SPH-000001', 'Almaz', 'female', 0, 'cash', 'opd', "
            "'enc:v1:1:abc', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"))
    with pytest.raises(RuntimeError, match="decrypt-existing"):
        command.downgrade(config, "0007")
    with get_engine().begin() as connection:
        connection.execute(text("UPDATE patients SET diagnosis = 'Malaria'"))
    command.downgrade(config, "0007")
    with get_engine().connect() as connection:
        assert connection.execute(text("SELECT diagnosis FROM patients")).scalar() == "Malaria"
    dbmod.reset_engine()


# --- the outbox ----------------------------------------------------------------------------------------

def test_sent_outbox_rows_are_deleted_after_a_day(client, hospital, doctor, patient, bus):
    link_directly(patient["id"], "DE482731")
    add(client, doctor, patient["id"])
    assert len(events(bus, "record.published")) == 1  # published (and still in the outbox)
    add(client, doctor, patient["id"], {**DIAGNOSIS, "title": "Not sent yet"})  # waits in the outbox
    with platform_session() as session:
        rows = session.scalars(select(OutboxEvent)).all()
        assert len(rows) == 2 and sum(r.published_at is not None for r in rows) == 1
    assert eventbus.purge_published() == 0  # sent just now: kept for a day
    with platform_session() as session:
        session.execute(update(OutboxEvent).where(OutboxEvent.published_at.is_not(None))
                        .values(published_at=utcnow() - eventbus.KEEP_PUBLISHED_FOR - timedelta(minutes=1)))
    assert eventbus.purge_published() == 1
    with platform_session() as session:
        [left] = session.scalars(select(OutboxEvent)).all()
        assert left.published_at is None and "Not sent yet" in left.payload  # unsent: kept until sent
    eventbus.housekeeping(bus)  # the worker's hourly run purges too
    assert len(events(bus, "record.published")) == 2


def test_files_of_unattached_uploads_are_encrypted_too(client, hospital, doctor, patient):
    file_id = upload(client, doctor, patient["id"], PDF, "loose.pdf").json()["id"]
    assert files.path_for(hospital, file_id).read_bytes().startswith(crypto.FILE_MAGIC)
    with session_scope(hospital) as session:
        assert session.get(RecordFile, file_id).filename == "loose.pdf"
    [(stored,)] = raw("SELECT filename FROM record_files")
    assert crypto.is_sealed(stored)


def test_shared_copies_and_import_plans_are_encrypted(client, hospital, doctor, patient, bus):
    from history_support import consume, send

    send(bus, "records.shared", {
        "share_id": "a" * 32, "hospital_id": hospital, "dedan_id": "DE482731", "patient_name": "Almaz Tefera",
        "records": [{"record_id": "b" * 32, "origin": "Other Clinic", "category": "diagnosis",
                     "title": f"{MARK} shared", "details": {"condition": f"{MARK} condition"},
                     "occurred_at": "2026-10-01T10:00:00+00:00",
                     "files": [{"file_id": "c" * 32, "filename": f"{MARK}.pdf", "content_type": "application/pdf",
                                "size": 10, "sha256": "0" * 64}]}]})
    consume(bus)
    [(title, details, listed)] = raw("SELECT title, details, files FROM shared_records")
    assert all(crypto.is_sealed(v) and MARK not in v for v in (title, details, listed))
    [share] = client.get("/shared", headers=doctor).json()["items"]
    assert share["records"][0]["title"] == f"{MARK} shared"
    assert share["records"][0]["details"]["condition"] == f"{MARK} condition"
    assert share["records"][0]["files"][0]["filename"] == f"{MARK}.pdf"

    link_directly(patient["id"], "DE482731")
    admin = staff(client, hospital, "admin")
    def preview(condition):
        csv = (f"mrn,category,title,occurred_at,condition\n"
               f"{patient['mrn']},diagnosis,{MARK} imported,2026-10-01,{condition}\n").encode()
        resp = client.post("/imports/preview", headers={**admin, "Content-Type": "text/csv", "X-Filename": "a.csv"},
                           content=csv)
        assert resp.status_code == 201, resp.text
        return resp.json()

    first = preview(f"{MARK} condition")
    assert [i["title"] for i in first["items"]] == [f"{MARK} imported"]
    assert all(crypto.is_sealed(p) and MARK not in p for (p,) in raw("SELECT plan FROM import_batches"))
    assert client.post(f"/imports/{first['import_id']}/confirm", headers=admin).json()["imported"] == 1
    # The same record from another source row: found by its (decrypted) title and skipped.
    again = preview("worded differently")
    assert again["items"] == [] and again["skipped"][0]["reason"] == "already imported"


# --- enforcement ---------------------------------------------------------------------------------------

def _alert(client, hospital, patient, label="Penicillin"):
    resp = client.post(f"/patients/{patient['id']}/alerts", headers=staff(client, hospital, "nurse"),
                       json={"kind": "allergy", "label": label})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_raw(table, column, row_id, value):
    with platform_session() as session:
        session.execute(text(f"UPDATE {table} SET {column} = :v WHERE id = :id"), {"v": value, "id": row_id})


def test_a_legacy_value_that_starts_with_the_prefix_still_loads_and_is_encrypted(client, hospital, doctor, patient):
    from app.models import PatientAlert

    record = add(client, doctor, patient["id"])
    legacy = "enc:v1: see the scanned allergy card"
    for value in (legacy, "enc:v1:1:not base64!", "enc:v1:1:QUJD"):  # malformed: plain text from before
        _set_raw("clinical_records", "title", record["id"], value)
        got = client.get(f"/patients/{patient['id']}/records", headers=doctor).json()["items"][0]
        assert got["title"] == value
    assert not crypto.is_sealed(legacy) and not crypto.is_sealed("enc:v1:0:" + "A" * 40)
    clean, lines = rekey.check()
    assert not clean and "clinical_records.title: 1 values, 1 plain text, 0 on an older key" in lines
    rekey.encrypt_existing()
    [(stored,)] = raw("SELECT title FROM clinical_records")
    assert crypto.is_sealed(stored) and rekey.check()[0]
    got = client.get(f"/patients/{patient['id']}/records", headers=doctor).json()["items"][0]
    assert got["title"] == "enc:v1:1:QUJD"
    alert = _alert(client, hospital, patient)
    with session_scope(hospital) as session:
        assert session.get(PatientAlert, alert["id"]).label == "Penicillin"


def test_enforcement_refuses_plaintext_values_and_files(client, hospital, doctor, patient, caplog):
    file_id = upload(client, doctor, patient["id"], PNG, "scan.png").json()["id"]
    record = add(client, doctor, patient["id"], {**DIAGNOSIS, "file_ids": [file_id]})
    rekey.decrypt_existing()
    enforced, _lines = rekey.enforce()
    assert enforced is False and rekey.is_enforced() is False  # plain text left: refused to enforce
    rekey.encrypt_existing()
    assert rekey.enforce()[0] is True and rekey.is_enforced() is True
    assert "enforced: yes" in rekey.check()[1]
    _reads_back(client, doctor, patient, record, file_id)

    # Plain text written behind the app's back is refused, and logged without the value.
    _set_raw("clinical_records", "title", record["id"], f"{MARK} written in plain text")
    with pytest.raises(crypto.CryptoError, match="not encrypted, and encryption is enforced"):
        client.get(f"/patients/{patient['id']}/records", headers=doctor)
    assert f"clinical_records.title of row {record['id']}" in caplog.text and MARK not in caplog.text
    _set_raw("clinical_records", "title", record["id"], crypto.seal(
        key_for(hospital), DIAGNOSIS["title"], "clinical_records", "title", record["id"]))
    files.path_for(hospital, file_id).write_bytes(PNG)
    with pytest.raises(crypto.CryptoError, match=f"File {file_id} is not encrypted"):
        client.get(f"/records/{record['id']}/files/{file_id}", headers=doctor)

    # Rolling back lifts enforcement first.
    rekey.decrypt_existing()
    assert rekey.is_enforced() is False


def test_the_enforce_command(client, hospital, doctor, patient, capsys):
    from app import cli

    add(client, doctor, patient["id"])
    rekey.decrypt_existing()
    with pytest.raises(SystemExit, match="Not enforced"):
        cli.main(["enforce-encryption"])
    assert cli.main(["encrypt-existing"]) == 0
    assert cli.main(["enforce-encryption"]) == 0
    out = capsys.readouterr().out
    assert "Master key fingerprint: " in out and "Enforced:" in out


# --- keys: savepoints, failed flushes, stale caches -------------------------------------------------

def raw_count_keys(session):
    return session.execute(text("SELECT count(*) FROM hospital_keys")).scalar()


def test_a_key_created_in_a_rolled_back_savepoint_is_never_used(client, hospital, patient):
    from app.models import PatientAlert

    with session_scope(hospital) as session:
        with pytest.raises(RuntimeError):
            with session.begin_nested():
                session.add(PatientAlert(hospital_id=hospital, patient_id=patient["id"], kind="allergy",
                                         label="first"))
                session.flush()  # creates the hospital's first key, in the savepoint
                assert raw_count_keys(session) == 1
                raise RuntimeError("the savepoint fails")
        assert raw_count_keys(session) == 0  # the key went with the savepoint
        session.add(PatientAlert(hospital_id=hospital, patient_id=patient["id"], kind="allergy", label="second"))
    crypto.clear_cache()  # as another process would: only the database counts
    with session_scope(hospital) as session:
        assert [a.label for a in session.scalars(select(PatientAlert))] == ["second"]


def test_a_failed_flush_encrypts_again_with_the_key_of_the_next_flush(client, hospital, patient):
    from sqlalchemy.exc import IntegrityError

    from app.models import Hospital, PatientAlert

    with platform_session() as session:
        alert = PatientAlert(hospital_id=hospital, patient_id=patient["id"], kind="allergy", label=f"{MARK} alert")
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(alert)
                session.add(Hospital(code="SPH", name="Duplicate code", timezone="Africa/Addis_Ababa"))
                session.flush()  # encrypts the alert under a new key (in the savepoint), then fails
        assert alert.label == f"{MARK} alert"  # plain again, not ciphertext under a key that is gone
        assert raw_count_keys(session) == 0
        session.add(alert)  # tried again, without the duplicate
        alert_id = alert.id
    crypto.clear_cache()
    with session_scope(hospital) as session:
        assert session.get(PatientAlert, alert_id).label == f"{MARK} alert"
    [(stored,)] = raw("SELECT label FROM patient_alerts")
    assert crypto.is_sealed(stored) and MARK not in stored
    assert len(raw("SELECT id FROM hospital_keys")) == 1


def _poison_cache():
    """Every cached data key replaced by a wrong one (a stale cache)."""
    with crypto._dek_lock:
        for key, (_dek, until) in list(crypto._dek_cache.items()):
            crypto._dek_cache[key] = (os.urandom(32), until)


def test_a_stale_cached_key_is_evicted_and_the_read_retried(client, hospital, doctor, patient):
    file_id = upload(client, doctor, patient["id"], PNG, "scan.png").json()["id"]
    record = add(client, doctor, patient["id"], {**DIAGNOSIS, "file_ids": [file_id]})
    assert crypto._dek_cache
    _poison_cache()
    got = client.get(f"/patients/{patient['id']}/records", headers=doctor).json()["items"][0]
    assert got["details"]["notes"] == f"{MARK} notes"
    _poison_cache()
    download = client.get(f"/records/{record['id']}/files/{file_id}", headers=doctor)
    assert download.status_code == 200 and download.content == PNG
    _poison_cache()
    version, report = rekey.rotate_key(hospital)  # the jobs read through the same retry
    assert version == 2 and report.files == {"encrypted": 1}
    _reads_back(client, doctor, patient, record, file_id)


def test_rotate_resume_moves_stragglers_without_a_new_key(client, hospital, doctor, patient):
    record, file_id = _seed(client, hospital, doctor, patient)
    with platform_session() as session:
        old = crypto.active_key(session, hospital)
        crypto.add_key_version(session, hospital, activate=True)  # as if a rotation started
    # An upload that started before: stored with the key active then (still kept, still readable).
    late = upload(client, doctor, patient["id"], PNG, "late.png").json()["id"]
    files.store_bytes(PNG, hospital, late, old)
    _reads_back(client, doctor, patient, record, file_id)
    version, report = rekey.rotate_key(hospital, new_key=False)
    assert version == 2 and report.files.get("encrypted", 0) >= 2
    assert raw("SELECT count(*) FROM hospital_keys")[0][0] == 2
    assert rekey.check()[0] and all("0 on an older key" in line for line in rekey.check()[1] if "values" in line)


# --- Redis -------------------------------------------------------------------------------------------

def test_events_are_deleted_from_redis_once_every_group_acknowledged_them(bus):
    from app.eventbus import STREAM_OUT, purge_acknowledged

    ids = [bus.xadd(STREAM_OUT, {"n": str(i)}) for i in range(5)]
    assert purge_acknowledged(bus, STREAM_OUT) == 0  # nobody has read them: kept
    bus.xgroup_create(STREAM_OUT, "platform", id="0")
    bus.xgroup_create(STREAM_OUT, "audit", id="0")
    read = bus.xreadgroup("platform", "p1", {STREAM_OUT: ">"}, count=4)
    platform_ids = [i for i, _f in read[0][1]]
    bus.xack(STREAM_OUT, "platform", *platform_ids[:3])  # the 4th is still pending
    bus.xreadgroup("audit", "a1", {STREAM_OUT: ">"}, count=2)
    bus.xack(STREAM_OUT, "audit", ids[0], ids[1])
    assert purge_acknowledged(bus, STREAM_OUT) == 2  # both groups are done with the first two only
    assert [i for i, _f in bus.xrange(STREAM_OUT)] == ids[2:]
    bus.xreadgroup("audit", "a1", {STREAM_OUT: ">"})
    bus.xack(STREAM_OUT, "audit", *ids[2:])
    bus.xack(STREAM_OUT, "platform", platform_ids[3])
    assert purge_acknowledged(bus, STREAM_OUT) == 2  # the 5th was never delivered to "platform"
    assert [i for i, _f in bus.xrange(STREAM_OUT)] == ids[4:]


def test_incoming_events_are_deleted_after_they_are_acknowledged(client, hospital, bus):
    from history_support import consume, send

    send(bus, "unknown.event", {"note": MARK})
    consume(bus)
    assert bus.xrange("endod:patient") == []
    assert bus.xpending("endod:patient", "hospital-service")["pending"] == 0


def test_dead_letters_keep_ids_and_the_error_but_no_clinical_data(client, hospital, bus):
    from history_support import consume, dead_letters, send

    send(bus, "records.shared", {"share_id": "not valid", "hospital_id": hospital, "patient_name": "Almaz Tefera",
                                 "records": [{"title": f"{MARK} shared"}], "phone": "+251911234567"},
         event_id="e" * 32)
    consume(bus)
    [(_id, entry)] = dead_letters(bus)
    assert entry["id"] == "e" * 32 and entry["type"] == "records.shared" and entry["error"]
    assert "payload" not in entry and len(entry["error"]) <= eventbus.DEAD_LETTER_ERROR_CHARS
    shown = json.loads(entry["payload_redacted"])
    assert shown["hospital_id"] == hospital and shown["records"] == "<list>" and shown["phone"] == "<str>"
    assert shown["patient_name"] == "<str>" and shown["share_id"] == "<str>"  # not id-like: not shown
    flat = json.dumps(entry)
    assert MARK not in flat and "Almaz" not in flat and "911234567" not in flat
    assert bus.xrange("endod:patient") == []  # acknowledged, then deleted
    huge = eventbus.redacted_payload(json.dumps({f"k{i}_id": "x" * 64 for i in range(200)}))
    assert len(huge) <= eventbus.DEAD_LETTER_PAYLOAD_CHARS
    assert eventbus.redacted_payload("not json") == '{"unparseable_bytes": 8}'
