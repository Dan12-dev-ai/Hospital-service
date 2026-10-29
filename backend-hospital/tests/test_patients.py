import pytest

from conftest import make_hospital, make_staff, sign_in

ALMAZ = {"full_name": "Almaz Tefera Kebede", "full_name_am": "አልማዝ ተፈራ", "sex": "female",
         "age_years": 48, "phone": "0911 234 567", "payer": "cbhi", "payer_number": "CBHI-AA-0042"}


@pytest.fixture
def desk(client, hospital):
    make_staff(hospital, "desk@sph.example", role="reception")
    return sign_in(client, "desk@sph.example")


@pytest.fixture
def nurse(client, hospital):
    make_staff(hospital, "nurse@sph.example", role="nurse")
    return sign_in(client, "nurse@sph.example")


def register(client, headers, **overrides):
    resp = client.post("/patients", headers=headers, json={**ALMAZ, **overrides})
    assert resp.status_code == 201, resp.text
    return resp.json()


def link_directly(patient_id, dedan_id):
    """As if Endod had confirmed the link (patient.linked)."""
    from app.db import platform_session
    from app.models import Patient

    with platform_session() as session:
        session.get(Patient, patient_id).dedan_id = dedan_id


def make_ward(client, admin, name="Ward B", capacity=2):
    return client.post("/departments", headers=admin,
                       json={"kind": "ward", "name": name, "capacity": capacity}).json()["id"]


class TestRegistration:
    def test_register_issues_hospital_numbers_in_order(self, client, desk):
        first = register(client, desk)
        second = register(client, desk, full_name="Dawit Bekele", phone="0922 000 111", sex="male")
        assert first["mrn"] == "SPH-000001" and second["mrn"] == "SPH-000002"
        assert first["phone"] == "+251911234567" and first["status"] == "opd"
        assert first["age_years"] == 48 and first["dob_estimated"] is True
        assert first["payer"] == "cbhi" and first["alerts"] == []

    def test_numbers_are_per_hospital(self, client, desk):
        register(client, desk)
        other = make_hospital(code="BLH", name="Black Lion")
        make_staff(other, "desk@blh.example", role="reception")
        assert register(client, sign_in(client, "desk@blh.example"))["mrn"] == "BLH-000001"

    @pytest.mark.parametrize("bad", [
        {"sex": "other"}, {"payer": "barter"}, {"phone": "12345"}, {"full_name": " "},
        {"date_of_birth": "2999-01-01", "age_years": None}, {"dedan_id": "not an id!"},
        {"date_of_birth": "1980-01-01"},  # together with age_years
    ])
    def test_invalid_registrations(self, client, desk, bad):
        assert client.post("/patients", headers=desk, json={**ALMAZ, **bad}).status_code in (400, 422)

    def test_same_name_and_phone_needs_confirmation(self, client, desk):
        first = register(client, desk)
        again = client.post("/patients", headers=desk, json={**ALMAZ, "full_name": "almaz tefera kebede"})
        assert again.status_code == 409 and first["mrn"] in again.json()["error"]
        assert register(client, desk, confirm_duplicate=True)["mrn"] == "SPH-000002"

    def test_a_typed_endod_id_is_only_a_claim(self, client, desk):
        # Endod confirms the account first (POST /patients/{id}/link, see test_linking.py);
        # an ID typed at registration (older clients send it as dedan_id) is kept as a claim.
        patient = register(client, desk, dedan_id="de-482731")
        assert patient["dedan_id"] is None and patient["claimed_dedan_id"] == "DE482731"
        other = register(client, desk, full_name="Dawit Bekele", claimed_dedan_id="DE 111 111".replace(" ", ""))
        assert other["dedan_id"] is None and other["claimed_dedan_id"] == "DE111111"

        resp = client.patch(f"/patients/{other['id']}", headers=desk, json={"dedan_id": "DE-222222"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["dedan_id"] is None and resp.json()["claimed_dedan_id"] == "DE222222"
        # Found by the ID given, and shown as given (not linked).
        found = client.get("/patients", headers=desk, params={"q": "DE-222222"}).json()["items"]
        assert [(p["id"], p["dedan_id"], p["claimed_dedan_id"]) for p in found] == [(other["id"], None, "DE222222")]

    def test_null_clears_the_claim_and_never_unlinks(self, client, desk):
        patient = register(client, desk, claimed_dedan_id="DE111111")
        link_directly(patient["id"], "DE482731")
        resp = client.patch(f"/patients/{patient['id']}", headers=desk, json={"dedan_id": None})
        assert resp.status_code == 200
        assert resp.json()["dedan_id"] == "DE482731" and resp.json()["claimed_dedan_id"] is None

    @pytest.mark.parametrize("bad", ["not an id!", "DE-4827311", "482731"])
    def test_a_claim_must_look_like_an_endod_id(self, client, desk, bad):
        for field in ("dedan_id", "claimed_dedan_id"):
            assert client.post("/patients", headers=desk, json={**ALMAZ, field: bad}).status_code == 422
        patient = register(client, desk)
        assert client.patch(f"/patients/{patient['id']}", headers=desk, json={"dedan_id": bad}).status_code == 422

    def test_only_stored_form_endod_ids_reach_the_database_or_the_bus(self, client, desk):
        from app import eventbus
        from app.db import platform_session
        from app.models import ClinicalRecord, Patient, QueueEntry, RecordShare, Visit

        patient = register(client, desk)
        with platform_session() as session:
            row = session.get(Patient, patient["id"])
            for bad in ("DE-482731", "de482731", "DE4827310", "x" * 40):
                with pytest.raises(ValueError):
                    row.dedan_id = bad
                for model, column in ((ClinicalRecord, "published_dedan_id"), (ClinicalRecord, "previous_dedan_id"),
                                      (Visit, "follow_up_sent_to"), (QueueEntry, "dedan_id"),
                                      (RecordShare, "dedan_id")):
                    with pytest.raises(ValueError):
                        setattr(model(), column, bad)
                with pytest.raises(ValueError):
                    eventbus.emit(session, "record.published", {"dedan_id": bad})
            row.dedan_id = "DE482731"
            row.dedan_id = None

    def test_pharmacists_cannot_register(self, client, hospital):
        make_staff(hospital, "rx@sph.example", role="pharmacist")
        assert client.post("/patients", headers=sign_in(client, "rx@sph.example"), json=ALMAZ).status_code == 403


class TestDirectory:
    def test_search_by_name_mrn_endod_id_and_phone(self, client, desk):
        almaz = register(client, desk)
        link_directly(almaz["id"], "DE482731")
        register(client, desk, full_name="Dawit Bekele", full_name_am="ዳዊት", phone="0922 000 111", sex="male")
        for q in ("almaz", "አልማዝ", almaz["mrn"].lower(), "de-4827", "0911234567", "+251 911 234 567", "0911"):
            found = client.get("/patients", headers=desk, params={"q": q}).json()
            assert [p["mrn"] for p in found["items"]] == [almaz["mrn"]], q
        assert client.get("/patients", headers=desk).json()["total"] == 2

    def test_paging(self, client, desk):
        for i in range(3):
            register(client, desk, full_name=f"Patient Number {i}", phone=f"091100000{i}")
        page = client.get("/patients", headers=desk, params={"limit": 2, "offset": 2}).json()
        assert page["total"] == 3 and len(page["items"]) == 1

    def test_stats(self, client, desk):
        register(client, desk)
        stats = client.get("/patients/stats", headers=desk).json()
        assert stats["total"] == 1 and stats["registered_today"] == 1 and stats["by_status"]["opd"] == 1

    def test_viewing_a_record_is_logged(self, client, desk):
        from sqlalchemy import select

        from app.db import platform_session
        from app.models import AuditEvent

        patient = register(client, desk)
        assert client.get(f"/patients/{patient['id']}", headers=desk).json()["mrn"] == patient["mrn"]
        with platform_session() as session:
            actions = session.scalars(select(AuditEvent.action).where(AuditEvent.target_id == patient["id"])).all()
        assert "patient_viewed" in actions

    def test_other_hospitals_patients_are_out_of_reach(self, client, desk):
        patient = register(client, desk)
        other = make_hospital(code="BLH", name="Black Lion")
        make_staff(other, "desk@blh.example", role="reception")
        stranger = sign_in(client, "desk@blh.example")
        assert client.get(f"/patients/{patient['id']}", headers=stranger).status_code == 404
        assert client.patch(f"/patients/{patient['id']}", headers=stranger, json={"address": "x"}).status_code == 404
        assert client.get("/patients", headers=stranger).json()["total"] == 0


class TestCare:
    def test_admit_assign_and_discharge(self, client, admin, desk, nurse, hospital):
        ward = make_ward(client, admin)
        doctor_id = make_staff(hospital, "doc@sph.example", role="doctor")
        patient = register(client, desk)
        admitted = client.patch(f"/patients/{patient['id']}", headers=nurse, json={
            "status": "admitted", "ward_id": ward, "bed": "12-A", "attending_doctor_id": doctor_id,
            "diagnosis": "Gastritis"})
        assert admitted.status_code == 200, admitted.text
        body = admitted.json()
        assert body["ward"]["name"] == "Ward B" and body["bed"] == "12-A"
        assert body["attending_doctor"]["id"] == doctor_id
        listed = client.get("/patients", headers=nurse, params={"status": "admitted", "ward_id": ward}).json()
        assert listed["total"] == 1

        gone = client.patch(f"/patients/{patient['id']}", headers=nurse, json={"status": "discharged"}).json()
        assert gone["ward"] is None and gone["bed"] is None and gone["attending_doctor"]["id"] == doctor_id

    def test_admission_needs_a_ward_and_a_free_bed(self, client, admin, desk, nurse):
        ward = make_ward(client, admin, capacity=2)
        a, b, c = (register(client, desk, full_name=f"Patient {n}", phone=f"091100000{i}")
                   for i, n in enumerate("ABC"))
        url = "/patients/{}"
        assert client.patch(url.format(a["id"]), headers=nurse, json={"status": "admitted"}).status_code == 400
        assert client.patch(url.format(a["id"]), headers=nurse,
                            json={"status": "admitted", "ward_id": ward, "bed": "1"}).status_code == 200
        taken = client.patch(url.format(b["id"]), headers=nurse, json={"status": "admitted", "ward_id": ward, "bed": "1"})
        assert taken.status_code == 409 and "taken" in taken.json()["error"]
        assert client.patch(url.format(b["id"]), headers=nurse,
                            json={"status": "admitted", "ward_id": ward, "bed": "2"}).status_code == 200
        full = client.patch(url.format(c["id"]), headers=nurse, json={"status": "admitted", "ward_id": ward})
        assert full.status_code == 409 and "full" in full.json()["error"]
        # Moving within the ward is fine even when it is full.
        assert client.patch(url.format(b["id"]), headers=nurse, json={"bed": "3"}).status_code == 200

    def test_outpatients_have_no_bed(self, client, admin, desk, nurse):
        ward = make_ward(client, admin)
        patient = register(client, desk)
        resp = client.patch(f"/patients/{patient['id']}", headers=nurse, json={"ward_id": ward})
        assert resp.status_code == 400

    def test_only_doctors_can_attend(self, client, desk, nurse, hospital):
        patient = register(client, desk)
        other_nurse = make_staff(hospital, "n2@sph.example", role="nurse")
        resp = client.patch(f"/patients/{patient['id']}", headers=nurse, json={"attending_doctor_id": other_nurse})
        assert resp.status_code == 400

    def test_who_may_change_what(self, client, desk, nurse):
        patient = register(client, desk)
        url = f"/patients/{patient['id']}"
        assert client.patch(url, headers=desk, json={"status": "emergency"}).status_code == 403
        assert client.patch(url, headers=nurse, json={"phone": "0911 999 999"}).status_code == 403
        assert client.patch(url, headers=desk, json={"phone": "0911 999 999", "age_years": None}).json()["phone"] \
            == "+251911999999"
        assert client.patch(url, headers=nurse, json={"status": "emergency"}).json()["status"] == "emergency"

    def test_alerts(self, client, desk, nurse):
        patient = register(client, desk)
        url = f"/patients/{patient['id']}/alerts"
        assert client.post(url, headers=desk, json={"kind": "allergy", "label": "Penicillin"}).status_code == 403
        assert client.post(url, headers=nurse, json={"kind": "mood", "label": "Sad"}).status_code == 400
        alert = client.post(url, headers=nurse, json={"kind": "allergy", "label": "Penicillin Allergy"}).json()
        shown = client.get(f"/patients/{patient['id']}", headers=nurse).json()["alerts"]
        assert shown == [{"id": alert["id"], "kind": "allergy", "label": "Penicillin Allergy"}]
        assert client.delete(f"{url}/{alert['id']}", headers=nurse).status_code == 200
        assert client.get(f"/patients/{patient['id']}", headers=nurse).json()["alerts"] == []


class TestReviewFixes:
    def test_directory_rows_leave_out_contact_and_payer_details(self, client, desk):
        register(client, desk)
        row = client.get("/patients", headers=desk).json()["items"][0]
        for hidden in ("phone", "address", "emergency_contact", "payer", "payer_number", "date_of_birth"):
            assert hidden not in row
        assert row["age_years"] == 48

    def test_searches_are_audited(self, client, desk):
        from sqlalchemy import select

        from app.db import platform_session
        from app.models import AuditEvent

        patient = register(client, desk)
        client.get("/patients", headers=desk, params={"q": patient["mrn"]})
        with platform_session() as session:
            event = session.scalar(select(AuditEvent).where(AuditEvent.action == "patients_searched"))
        assert event is not None and patient["id"] in event.detail

    def test_diagnosis_is_hidden_from_billing(self, client, desk, nurse, hospital):
        patient = register(client, desk)
        client.patch(f"/patients/{patient['id']}", headers=nurse, json={"diagnosis": "Malaria"})
        make_staff(hospital, "cash@sph.example", role="billing")
        cashier = sign_in(client, "cash@sph.example")
        assert client.get(f"/patients/{patient['id']}", headers=cashier).json()["diagnosis"] is None
        assert client.get(f"/patients/{patient['id']}", headers=nurse).json()["diagnosis"] == "Malaria"

    def test_moving_wards_drops_the_old_bed(self, client, admin, desk, nurse):
        ward_a, ward_b = make_ward(client, admin, "Ward A"), make_ward(client, admin, "Ward B")
        patient = register(client, desk)
        url = f"/patients/{patient['id']}"
        client.patch(url, headers=nurse, json={"status": "admitted", "ward_id": ward_a, "bed": "3"})
        moved = client.patch(url, headers=nurse, json={"ward_id": ward_b}).json()
        assert moved["ward"]["name"] == "Ward B" and moved["bed"] is None

    def test_birth_date_is_checked_against_the_hospital_date(self, client, desk, monkeypatch):
        from datetime import date, timedelta

        from app.api import patients

        today = date(2026, 3, 1)
        monkeypatch.setattr(patients, "_today", lambda hospital: today)
        assert register(client, desk, age_years=None, date_of_birth=today.isoformat())["age_years"] == 0
        tomorrow = (today + timedelta(days=1)).isoformat()
        resp = client.post("/patients", headers=desk, json={**ALMAZ, "age_years": None, "date_of_birth": tomorrow,
                                                          "full_name": "Not Born Yet"})
        assert resp.status_code == 400

    def test_empty_age_is_not_a_change(self, client, desk):
        patient = register(client, desk)
        assert client.patch(f"/patients/{patient['id']}", headers=desk, json={"age_years": None}).status_code == 400

    def test_identity_changes_keep_the_old_value(self, client, desk):
        import json

        from sqlalchemy import select

        from app.db import platform_session
        from app.models import AuditEvent

        patient = register(client, desk, claimed_dedan_id="DE482731")
        client.patch(f"/patients/{patient['id']}", headers=desk, json={"claimed_dedan_id": None, "address": "Bole"})
        with platform_session() as session:
            detail = json.loads(session.scalar(select(AuditEvent.detail).where(AuditEvent.action == "patient_updated")))
        assert detail["identity"] == {"claimed_dedan_id": {"from": "DE482731", "to": None}}

    def test_wildcards_in_search_are_literal(self, client, desk):
        register(client, desk)
        assert client.get("/patients", headers=desk, params={"q": "%"}).json()["total"] == 0
        assert client.get("/patients", headers=desk, params={"q": "_"}).json()["total"] == 0
