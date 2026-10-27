"""Prescriptions dispensed at pharmacies (docs/pharmacy.md, section 4)."""

import uuid

import pytest

from conftest import make_hospital
from history_support import (  # noqa: F401  (fixtures)
    bus, consume, dead_letters, link_directly, platform_key, register, send, staff,
)

DEDAN = "DE482731"
PRESCRIPTION = {"category": "prescription", "title": "Malaria treatment", "details": {"items": [
    {"drug": "Artemether/lumefantrine", "dose": "80/480 mg", "frequency": "twice daily", "quantity": "24 tablets"},
    {"drug": "Paracetamol", "dose": "500 mg", "quantity": "as needed"},
]}}
DIAGNOSIS = {"category": "diagnosis", "title": "Malaria", "details": {"condition": "Malaria"}}


@pytest.fixture
def doctor(client, hospital):
    return staff(client, hospital, "doctor")


@pytest.fixture
def patient(client, hospital):
    patient = register(client, staff(client, hospital, "reception"))
    link_directly(patient["id"], DEDAN)
    return patient


@pytest.fixture
def prescription(client, doctor, patient):
    resp = client.post(f"/patients/{patient['id']}/records", headers=doctor, json=PRESCRIPTION)
    assert resp.status_code == 201, resp.text
    assert resp.json()["published"] is True
    return resp.json()


def dispensed(record_id, hospital_id, changes=None, **more):
    payload = {
        "record_id": record_id, "hospital_id": hospital_id, "dedan_id": DEDAN, "dispense_id": uuid.uuid4().hex,
        "at": "2026-10-23T14:10:00+03:00", "pharmacy_name": "Kenema Pharmacy", "status": "open",
        "items": [{"item_index": 0, "amount": 14, "complete": False, "given_total": 14, "status": "partly_given"}],
    }
    payload.update(changes or {}, **more)
    return payload


def records_of(client, headers, patient_id):
    resp = client.get(f"/patients/{patient_id}/records", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def pending(bus):
    return bus.xpending("endod:patient", "hospital-service")["pending"]


class TestHandler:
    def test_a_dispense_is_stored_and_shown_on_the_prescription(self, client, doctor, patient, prescription, bus,
                                                                 hospital):
        [record] = records_of(client, doctor, patient["id"])
        assert record["dispensing"] == {"status": "not_dispensed", "dispenses": []}
        payload = dispensed(prescription["id"], hospital)
        send(bus, "prescription.dispensed", payload)
        consume(bus)
        assert dead_letters(bus) == [] and pending(bus) == 0
        [record] = records_of(client, doctor, patient["id"])
        assert record["dispensing"] == {"status": "partly", "dispenses": [{
            "dispense_id": payload["dispense_id"], "at": "2026-10-23T11:10:00+00:00",
            "pharmacy_name": "Kenema Pharmacy", "status": "open",
            "items": [{"item_index": 0, "amount": 14, "complete": False, "given_total": 14, "status": "partly_given",
                       "drug": "Artemether/lumefantrine", "quantity_total": 24}],
        }]}

    def test_the_rest_given_elsewhere_completes_it(self, client, doctor, patient, prescription, bus, hospital):
        send(bus, "prescription.dispensed", dispensed(prescription["id"], hospital))
        send(bus, "prescription.dispensed", dispensed(
            prescription["id"], hospital, at="2026-10-24T09:00:00+03:00", pharmacy_name="  Bole Pharmacy ",
            status="completed", items=[
                {"item_index": 0, "amount": 10, "complete": False, "given_total": 24, "status": "given"},
                {"item_index": 1, "amount": None, "complete": True, "given_total": None, "status": "given"},
            ]))
        consume(bus)
        [record] = records_of(client, doctor, patient["id"])
        info = record["dispensing"]
        assert info["status"] == "fully"
        assert [d["pharmacy_name"] for d in info["dispenses"]] == ["Kenema Pharmacy", "Bole Pharmacy"]
        second = info["dispenses"][1]["items"]
        assert second[1] == {"item_index": 1, "amount": None, "complete": True, "given_total": None,
                             "status": "given", "drug": "Paracetamol", "quantity_total": None}

    def test_idempotent_on_dispense_id(self, client, doctor, patient, prescription, bus, hospital):
        payload = dispensed(prescription["id"], hospital)
        send(bus, "prescription.dispensed", payload)
        send(bus, "prescription.dispensed", payload)  # another event id, the same dispense
        send(bus, "prescription.dispensed", {**payload, "pharmacy_name": "Changed Pharmacy"})
        consume(bus)
        assert dead_letters(bus) == [] and pending(bus) == 0
        [record] = records_of(client, doctor, patient["id"])
        assert [d["pharmacy_name"] for d in record["dispensing"]["dispenses"]] == ["Kenema Pharmacy"]

    def test_a_dispense_id_reused_for_another_prescription_is_dead_lettered(self, client, doctor, patient,
                                                                           prescription, bus, hospital):
        other = client.post(f"/patients/{patient['id']}/records", headers=doctor, json=PRESCRIPTION).json()
        payload = dispensed(prescription["id"], hospital)
        send(bus, "prescription.dispensed", payload)
        send(bus, "prescription.dispensed", {**payload, "record_id": other["id"]})
        consume(bus)
        assert len(dead_letters(bus)) == 1
        by_id = {r["id"]: r for r in records_of(client, doctor, patient["id"])}
        assert by_id[other["id"]]["dispensing"]["dispenses"] == []

    def test_another_hospitals_record_is_dead_lettered(self, client, prescription, bus):
        other = make_hospital(code="TKH", name="Tikur Anbessa")
        send(bus, "prescription.dispensed", dispensed(prescription["id"], other))
        consume(bus)
        [entry] = dead_letters(bus)
        assert "another hospital" in entry[1]["error"]

    def test_an_unknown_hospital_is_dead_lettered(self, prescription, bus):
        send(bus, "prescription.dispensed", dispensed(prescription["id"], "nohospital"))
        consume(bus)
        assert len(dead_letters(bus)) == 1

    def test_a_record_that_is_not_a_prescription_is_dead_lettered(self, client, doctor, patient, bus, hospital):
        diagnosis = client.post(f"/patients/{patient['id']}/records", headers=doctor, json=DIAGNOSIS).json()
        send(bus, "prescription.dispensed", dispensed(diagnosis["id"], hospital))
        consume(bus)
        [entry] = dead_letters(bus)
        assert "not a prescription" in entry[1]["error"]

    def test_another_endod_account_is_dead_lettered(self, prescription, bus, hospital):
        send(bus, "prescription.dispensed", dispensed(prescription["id"], hospital, dedan_id="DE111111"))
        consume(bus)
        assert len(dead_letters(bus)) == 1

    def test_a_dispense_in_flight_when_the_record_was_retracted_from_the_account_is_kept(
            self, client, doctor, patient, prescription, bus, hospital):
        """Published, then taken off the account (re-link): a dispense Endod made
        just before it handled record.retracted is still stored."""
        from app import records
        from app.db import platform_session
        from app.models import ClinicalRecord

        with platform_session() as session:
            records.retract_from_platform(session, session.get(ClinicalRecord, prescription["id"]), DEDAN,
                                          "The hospital linked this record to a different Endod account.")
        kept = dispensed(prescription["id"], hospital)
        send(bus, "prescription.dispensed", kept)
        send(bus, "prescription.dispensed", dispensed(prescription["id"], hospital, dedan_id="DE111111"))
        consume(bus)
        [entry] = dead_letters(bus)
        assert "not sent to this Endod account" in entry[1]["error"]
        [record] = records_of(client, doctor, patient["id"])
        assert [d["dispense_id"] for d in record["dispensing"]["dispenses"]] == [kept["dispense_id"]]

    def test_after_a_re_link_to_another_account_both_accounts_count(self, client, doctor, patient, prescription,
                                                                     bus, hospital):
        """Re-linked and published to the new account in one step: the old
        account's in-flight dispense and the new account's both count."""
        new = "DE555555"
        link_directly(patient["id"], new)
        resp = client.patch(f"/records/{prescription['id']}", headers=doctor, json={"title": "Malaria treatment, v2"})
        assert resp.status_code == 200, resp.text
        old_one = dispensed(prescription["id"], hospital)
        new_one = dispensed(prescription["id"], hospital, dedan_id=new)
        for payload in (old_one, new_one, dispensed(prescription["id"], hospital, dedan_id="DE111111")):
            send(bus, "prescription.dispensed", payload)
        consume(bus)
        assert len(dead_letters(bus)) == 1
        [record] = records_of(client, doctor, patient["id"])
        assert {d["dispense_id"] for d in record["dispensing"]["dispenses"]} == {old_one["dispense_id"],
                                                                                 new_one["dispense_id"]}

    def test_an_unknown_record_is_retried_then_dead_lettered(self, prescription, bus, hospital, monkeypatch):
        from app import eventbus

        monkeypatch.setattr(eventbus, "RETRY_AFTER_MS", 0)
        send(bus, "prescription.dispensed", dispensed(uuid.uuid4().hex, hospital))
        for attempt in range(1, eventbus.MAX_DELIVERIES):
            consume(bus)
            assert pending(bus) == 1 and dead_letters(bus) == [], attempt
        consume(bus)
        assert pending(bus) == 0
        [entry] = dead_letters(bus)
        assert "RetryLater" in entry[1]["error"]

    @pytest.mark.parametrize("change", [
        {"record_id": "not-hex"},
        {"dedan_id": "nonsense"},
        {"dispense_id": ""},
        {"dispense_id": "has spaces"},
        {"at": "2026-10-23T14:10:00"},  # no offset
        {"pharmacy_name": " x "},
        {"pharmacy_name": "x" * 121},
        {"status": "expired"},
        {"items": []},
        {"items": [{"item_index": 0, "amount": -1, "complete": False, "given_total": 0, "status": "not_given"}]},
        {"items": [{"item_index": 30, "amount": 1, "complete": False, "given_total": 1, "status": "partly_given"}]},
        {"items": [{"item_index": 0, "amount": 1, "complete": False, "given_total": 1, "status": "half"}]},
        {"items": [{"item_index": 0, "amount": 1, "complete": False, "given_total": 1, "status": "given"},
                   {"item_index": 0, "amount": 1, "complete": False, "given_total": 2, "status": "given"}]},
    ])
    def test_malformed_payloads_are_dead_lettered(self, client, doctor, patient, prescription, bus, hospital,
                                                  change):
        send(bus, "prescription.dispensed", dispensed(prescription["id"], hospital, change))
        consume(bus)
        assert len(dead_letters(bus)) == 1 and pending(bus) == 0
        [record] = records_of(client, doctor, patient["id"])
        assert record["dispensing"]["dispenses"] == []


class TestRoles:
    def test_who_sees_the_dispenses(self, client, hospital, patient, prescription, bus):
        send(bus, "prescription.dispensed", dispensed(prescription["id"], hospital))
        consume(bus)
        for role in ("admin", "doctor2", "nurse", "pharmacist", "records"):
            headers = staff(client, hospital, "doctor" if role == "doctor2" else role, name=role)
            [record] = records_of(client, headers, patient["id"])
            assert record["dispensing"]["status"] == "partly", role
        for role in ("reception2", "billing"):
            headers = staff(client, hospital, "reception" if role == "reception2" else role, name=role)
            assert client.get(f"/patients/{patient['id']}/records", headers=headers).status_code == 403, role

    def test_other_categories_have_no_dispensing(self, client, doctor, patient):
        resp = client.post(f"/patients/{patient['id']}/records", headers=doctor, json=DIAGNOSIS)
        assert resp.json()["dispensing"] is None

    def test_another_hospital_cannot_see_them(self, client, patient, prescription):
        other = make_hospital(code="TKH", name="Tikur Anbessa")
        headers = staff(client, other, "pharmacist", name="tkh-pharmacist")
        assert client.get(f"/patients/{patient['id']}/records", headers=headers).status_code == 404


def test_quantity_total_is_the_leading_number():
    from app.dispensing import quantity_total

    assert quantity_total("21 tablets") == 21
    assert quantity_total("2.5 ml") == 2.5
    assert quantity_total("as needed") is None
    assert quantity_total(None) is None


def test_migration_0006_adds_the_table_and_keeps_everything_else(tmp_path, monkeypatch):
    """A new table and an added column only: existing rows are kept, up and down (SQLite)."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect, text

    from app import db as dbmod
    from app.db import get_engine

    monkeypatch.setenv("HOSPITAL_DATABASE_URL", f"sqlite:///{tmp_path / 'before-0006.db'}")
    dbmod.reset_engine()
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "0005")
    record_id = "a" * 32
    with get_engine().begin() as connection:
        connection.execute(text("INSERT INTO hospitals (id, code, name, timezone, created_at, status, facility_type) "
                                "VALUES ('h1', 'SPH', 'St. Paul', 'Africa/Addis_Ababa', '2026-01-01 00:00:00', "
                                "'approved', 'hospital')"))
        connection.execute(text(
            "INSERT INTO patients (id, hospital_id, mrn, full_name, sex, dob_estimated, payer, status, "
            "created_at, updated_at) VALUES ('p1', 'h1', 'SPH-000001', 'Almaz', 'female', 0, 'cash', 'opd', "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"))
        connection.execute(text(
            "INSERT INTO clinical_records (id, hospital_id, patient_id, category, title, details, occurred_at, "
            "source, version, retracted, created_at, updated_at) VALUES (:id, 'h1', 'p1', 'prescription', 'Rx', "
            "'{\"items\": [{\"drug\": \"Amoxicillin\"}]}', '2026-01-01 00:00:00', 'portal', 1, 0, "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"), {"id": record_id})
    command.upgrade(config, "head")
    with get_engine().begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM hospitals")).scalar() == 1
        assert connection.execute(text("SELECT count(*) FROM patients")).scalar() == 1
        assert connection.execute(text("SELECT count(*) FROM clinical_records")).scalar() == 1
        assert connection.execute(text("SELECT previous_dedan_id FROM clinical_records")).scalar() is None
        connection.execute(text(
            "INSERT INTO prescription_dispenses (id, hospital_id, record_id, dedan_id, pharmacy_name, dispensed_at, "
            "status, items, received_at) VALUES ('d1', 'h1', :id, 'DE482731', 'Kenema', '2026-10-23 11:10:00', "
            "'open', '[]', '2026-10-23 11:10:00')"), {"id": record_id})
    command.downgrade(config, "0005")
    with get_engine().connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM patients")).scalar() == 1
        assert connection.execute(text("SELECT count(*) FROM clinical_records")).scalar() == 1
        tables = inspect(connection).get_table_names()
        record_columns = {c["name"] for c in inspect(connection).get_columns("clinical_records")}
    dbmod.reset_engine()
    assert "prescription_dispenses" not in tables
    assert "previous_dedan_id" not in record_columns
