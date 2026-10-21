"""Records shared with the hospital (section 5) and imports (section 6) of docs/history-events.md."""

import base64
import hashlib
import io
import json
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from history_support import (  # noqa: F401  (fixtures)
    PDF, PLATFORM_KEY, PNG, bus, consume, dead_letters, events, link_directly, platform_key, register, send, staff,
)


@pytest.fixture
def desk(client, hospital):
    return staff(client, hospital, "reception")


@pytest.fixture
def doctor(client, hospital):
    return staff(client, hospital, "doctor")


@pytest.fixture
def linked(client, desk):
    patient = register(client, desk)
    link_directly(patient["id"], "DE482731")
    return patient


def share_payload(hospital, share_id=None, expires_at=None, dedan="DE482731"):
    return {
        "share_id": share_id or uuid.uuid4().hex, "hospital_id": hospital, "dedan_id": dedan,
        "patient_name": "Almaz Tefera", "expires_at": expires_at,
        "records": [
            {"record_id": uuid.uuid4().hex, "origin": "Black Lion Hospital", "category": "lab_result",
             "title": "CBC", "details": {"items": [{"test": "Hemoglobin", "value": "9.1", "flag": "low"}]},
             "occurred_at": "2026-09-01T08:00:00+00:00", "recorded_by": "Dr. Sara",
             "files": [{"file_id": "a" * 32, "filename": "cbc.pdf", "content_type": "application/pdf",
                        "size": len(PDF), "sha256": hashlib.sha256(PDF).hexdigest()}]},
            {"record_id": uuid.uuid4().hex, "origin": "Self-reported", "category": "diagnosis",
             "title": "Asthma since childhood", "details": {"notes": "uses an inhaler"},
             "occurred_at": "2010-01-01T00:00:00+00:00", "recorded_by": None, "files": []},
        ],
    }


def shared(client, headers, patient_id=None):
    resp = client.get("/shared", headers=headers, params={"patient_id": patient_id} if patient_id else None)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


class TestSharing:
    def test_a_share_is_stored_and_shown_with_its_origin(self, client, doctor, linked, bus, hospital):
        payload = share_payload(hospital)
        send(bus, "records.shared", payload)
        consume(bus)
        [item] = shared(client, doctor)
        assert item["share_id"] == payload["share_id"] and item["patient"]["id"] == linked["id"]
        assert [r["origin"] for r in item["records"]] == ["Black Lion Hospital", "Self-reported"]
        # A sparse self-reported record is kept as the patient wrote it.
        assert item["records"][1]["details"] == {"notes": "uses an inhaler"}
        assert shared(client, doctor, linked["id"])[0]["share_id"] == payload["share_id"]

    def test_redelivery_replaces_the_copy(self, client, doctor, linked, bus, hospital):
        payload = share_payload(hospital)
        send(bus, "records.shared", payload, "evt-1")
        send(bus, "records.shared", payload, "evt-1")
        send(bus, "records.shared", payload, "evt-2")
        consume(bus)
        [item] = shared(client, doctor)
        assert len(item["records"]) == 2

    def test_unshared_deletes_the_copy(self, client, doctor, linked, bus, hospital):
        from sqlalchemy import func, select

        from app.db import session_scope
        from app.models import SharedRecord

        payload = share_payload(hospital)
        send(bus, "records.shared", payload)
        send(bus, "records.unshared", {"share_id": payload["share_id"], "hospital_id": hospital})
        consume(bus)
        assert shared(client, doctor) == []
        with session_scope() as session:
            assert session.scalar(select(func.count()).select_from(SharedRecord)) == 0

    def test_unshared_before_shared_keeps_nothing(self, client, doctor, linked, bus, hospital):
        payload = share_payload(hospital)
        send(bus, "records.unshared", {"share_id": payload["share_id"], "hospital_id": hospital})
        send(bus, "records.shared", payload)
        consume(bus)
        assert shared(client, doctor) == []
        assert dead_letters(bus) == []

    def test_expiry(self, client, doctor, linked, bus, hospital):
        from sqlalchemy import update

        from app import chores
        from app.db import session_scope
        from app.models import RecordShare

        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        send(bus, "records.shared", share_payload(hospital, expires_at=past))
        future = share_payload(hospital, expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        send(bus, "records.shared", future)
        consume(bus)
        assert [s["share_id"] for s in shared(client, doctor)] == [future["share_id"]]
        with session_scope() as session:
            session.execute(update(RecordShare).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        assert shared(client, doctor) == []  # hidden at once
        assert chores.run() >= 1  # and deleted by the worker

    @pytest.mark.parametrize("change", [
        {"share_id": "not-hex"}, {"hospital_id": "nope"}, {"dedan_id": "x"}, {"records": "nope"},
        {"expires_at": "2030-01-01T00:00:00"},
    ])
    def test_malformed_shares_are_dead_lettered(self, client, linked, bus, hospital, change):
        send(bus, "records.shared", {**share_payload(hospital), **change})
        consume(bus)
        assert len(dead_letters(bus)) == 1

    def test_who_sees_shared_records(self, client, hospital, linked, bus):
        send(bus, "records.shared", share_payload(hospital))
        consume(bus)
        for role, allowed in (("reception", False), ("billing", False), ("nurse", True), ("pharmacist", True),
                              ("records", True), ("admin", True)):
            resp = client.get("/shared", headers=staff(client, hospital, role, f"{role}-s"))
            assert (resp.status_code == 200) is allowed, role
        from conftest import make_hospital

        stranger = staff(client, make_hospital(code="BLH", name="Black Lion"), "doctor", "doc-blh")
        assert shared(client, stranger) == []
        assert client.get("/shared", headers=stranger, params={"patient_id": linked["id"]}).status_code == 404


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class TestSharedFiles:
    @pytest.fixture
    def share(self, client, linked, bus, hospital, monkeypatch):
        monkeypatch.setenv("HOSPITAL_PLATFORM_API_URL", "http://endod-platform-api:8000")
        payload = share_payload(hospital)
        send(bus, "records.shared", payload)
        consume(bus)
        return payload

    def _serve(self, monkeypatch, body=PDF, error=None):
        from app import sharing

        seen = []

        def fake_open(request):
            seen.append(request)
            if error:
                raise error
            return _Response(body)

        monkeypatch.setattr(sharing, "_open", fake_open)
        return seen

    def test_fetched_from_the_platform_on_demand(self, client, doctor, share, monkeypatch):
        seen = self._serve(monkeypatch)
        resp = client.get(f"/shared/{share['share_id']}/files/{'a' * 32}", headers=doctor)
        assert resp.status_code == 200 and resp.content == PDF
        assert resp.headers["content-type"] == "application/pdf"
        assert seen[0].full_url == f"http://endod-platform-api:8000/internal/shares/{share['share_id']}/files/{'a' * 32}"
        assert seen[0].get_header("X-platform-key") == PLATFORM_KEY

    @pytest.mark.parametrize("body", [PDF + b"extra", PDF[:-1] + b"X", PNG])
    def test_a_file_that_does_not_match_is_refused(self, client, doctor, share, monkeypatch, body):
        self._serve(monkeypatch, body=body)
        assert client.get(f"/shared/{share['share_id']}/files/{'a' * 32}", headers=doctor).status_code == 502

    def test_unshared_on_the_platform(self, client, doctor, share, monkeypatch):
        self._serve(monkeypatch, error=urllib.error.HTTPError("u", 410, "Gone", {}, None))
        assert client.get(f"/shared/{share['share_id']}/files/{'a' * 32}", headers=doctor).status_code == 404

    def test_only_listed_files_of_active_shares(self, client, doctor, share, monkeypatch, bus, hospital):
        seen = self._serve(monkeypatch)
        assert client.get(f"/shared/{share['share_id']}/files/{'b' * 32}", headers=doctor).status_code == 404
        send(bus, "records.unshared", {"share_id": share["share_id"], "hospital_id": hospital})
        consume(bus)
        assert client.get(f"/shared/{share['share_id']}/files/{'a' * 32}", headers=doctor).status_code == 404
        assert seen == []  # never asked the platform

    def test_not_configured(self, client, doctor, share, monkeypatch):
        monkeypatch.delenv("HOSPITAL_PLATFORM_API_URL")
        assert client.get(f"/shared/{share['share_id']}/files/{'a' * 32}", headers=doctor).status_code == 503


# --- imports -------------------------------------------------------------------------------

def bundle(mrn, *resources, extra_patients=()):
    patient = {"resourceType": "Patient", "id": "p1", "identifier": [{"system": "urn:his:mrn", "value": mrn}]}
    entries = [{"fullUrl": "urn:uuid:p1", "resource": patient}]
    entries += [{"resource": p} for p in extra_patients]
    entries += [{"resource": r} for r in resources]
    return json.dumps({"resourceType": "Bundle", "type": "collection", "entry": entries}).encode()


SUBJECT = {"reference": "urn:uuid:p1"}
RESOURCES = [
    {"resourceType": "Condition", "id": "c1", "subject": SUBJECT, "recordedDate": "2025-03-01",
     "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "E11.9",
                          "display": "Type 2 diabetes mellitus"}]},
     "clinicalStatus": {"coding": [{"code": "active"}]}, "recorder": {"display": "Dr. Abebe"}},
    {"resourceType": "MedicationRequest", "id": "m1", "subject": SUBJECT, "authoredOn": "2025-03-01T10:00:00+03:00",
     "medicationCodeableConcept": {"text": "Metformin 500 mg"},
     "dosageInstruction": [{"route": {"text": "oral"}, "timing": {"code": {"text": "twice daily"}},
                            "doseAndRate": [{"doseQuantity": {"value": 1, "unit": "tablet"}}]}],
     "dispenseRequest": {"quantity": {"value": 60, "unit": "tablets"}}},
    {"resourceType": "Observation", "id": "o1", "subject": SUBJECT, "effectiveDateTime": "2025-03-01T09:00:00Z",
     "category": [{"coding": [{"code": "laboratory"}]}], "code": {"text": "HbA1c"},
     "valueQuantity": {"value": 8.2, "unit": "%"}, "referenceRange": [{"low": {"value": 4}, "high": {"value": 5.6}}],
     "interpretation": [{"coding": [{"code": "H"}]}]},
    {"resourceType": "Observation", "id": "o2", "subject": SUBJECT, "effectiveDateTime": "2025-03-01",
     "category": [{"coding": [{"code": "vital-signs"}]}], "code": {"text": "Blood pressure"}},
    {"resourceType": "DiagnosticReport", "id": "r1", "subject": SUBJECT, "issued": "2025-02-20T12:00:00Z",
     "category": [{"coding": [{"code": "RAD"}, {"code": "CT", "display": "CT"}]}], "code": {"text": "CT abdomen"},
     "conclusion": "No acute findings."},
    {"resourceType": "DocumentReference", "id": "d1", "subject": SUBJECT, "date": "2025-02-01T08:00:00Z",
     "description": "Discharge summary",
     "content": [{"attachment": {"contentType": "application/pdf", "title": "summary.pdf",
                                 "data": base64.b64encode(PDF).decode()}}]},
    {"resourceType": "DocumentReference", "id": "d2", "subject": SUBJECT, "date": "2025-02-01",
     "content": [{"attachment": {"url": "https://his.example/doc/1"}}]},
    {"resourceType": "Encounter", "id": "e1", "subject": SUBJECT},
    {"resourceType": "Condition", "id": "c2", "subject": {"identifier": {"system": "urn:his:mrn", "value": "SPH-999999"}},
     "recordedDate": "2025-01-01", "code": {"text": "Asthma"}},
    {"resourceType": "Condition", "id": "c3", "subject": SUBJECT, "code": {"text": "No date"}},
]


def preview(client, headers, data, filename="bundle.json", content_type="application/fhir+json"):
    from urllib.parse import quote

    return client.post("/imports/preview", headers={**headers, "Content-Type": content_type,
                                                    "X-Filename": quote(filename)}, content=data)


class TestFhirImport:
    def test_preview_then_confirm(self, client, hospital, linked, bus):
        records_clerk = staff(client, hospital, "records")
        resp = preview(client, records_clerk, bundle(linked["mrn"], *RESOURCES))
        assert resp.status_code == 201, resp.text
        plan = resp.json()
        assert plan["format"] == "fhir"
        assert [(i["what"], i["category"]) for i in plan["items"]] == [
            ("Condition c1", "diagnosis"), ("MedicationRequest m1", "prescription"), ("Observation o1", "lab_result"),
            ("DiagnosticReport r1", "imaging"), ("DocumentReference d1", "document")]
        reasons = {s["what"]: s["reason"] for s in plan["skipped"]}
        assert reasons == {
            "Observation o2": "not a laboratory observation",
            "DocumentReference d2": "the document is not attached inline (base64)",
            "Encounter e1": "Encounter is not imported",
            "Condition c2": "no patient with hospital number SPH-999999",
            "Condition c3": "no date",
        }
        # Nothing saved before confirmation.
        assert events(bus, "record.published") == []
        doctor = staff(client, hospital, "doctor")
        assert client.get(f"/patients/{linked['id']}/records", headers=doctor).json()["items"] == []

        done = client.post(f"/imports/{plan['import_id']}/confirm", headers=records_clerk)
        assert done.status_code == 200 and done.json()["imported"] == 5
        published = {e["category"]: e for e in events(bus, "record.published")}
        assert all(e["source"] == "import" and e["dedan_id"] == "DE482731" for e in published.values())
        diagnosis = published["diagnosis"]
        assert diagnosis["details"] == {"condition": "Type 2 diabetes mellitus", "code": "E11.9", "status": "active",
                                        "notes": None}
        assert diagnosis["recorded_by"] == "Dr. Abebe" and diagnosis["occurred_at"] == "2025-02-28T21:00:00+00:00"
        assert published["prescription"]["details"]["items"][0] == {
            "drug": "Metformin 500 mg", "dose": "1 tablet", "route": "oral", "frequency": "twice daily",
            "duration": None, "quantity": "60 tablets", "notes": None}
        lab = published["lab_result"]["details"]["items"][0]
        assert lab == {"test": "HbA1c", "value": "8.2", "unit": "%", "reference_range": "4-5.6", "flag": "high"}
        assert published["imaging"]["details"]["modality"] == "CT"
        assert published["imaging"]["details"]["findings"] == "No acute findings."
        [document_file] = published["document"]["files"]
        assert document_file["sha256"] == hashlib.sha256(PDF).hexdigest()
        assert document_file["filename"] == "summary.pdf"

        assert client.post(f"/imports/{plan['import_id']}/confirm", headers=records_clerk).status_code == 409
        again = preview(client, records_clerk, bundle(linked["mrn"], *RESOURCES)).json()
        assert again["items"] == [] and {s["reason"] for s in again["skipped"]} >= {"already imported"}

    def test_matching_by_endod_id_and_linked_patients_only(self, client, admin, desk, linked):
        unlinked = register(client, desk, name="Not Linked", phone="0922000111")
        endod = {"resourceType": "Patient", "id": "p2",
                 "identifier": [{"system": "https://endod-health.com/id", "value": "DE482731"}]}
        resources = [
            {"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/p2"},
             "recordedDate": "2025-01-01", "code": {"text": "Hypertension"}},
            {"resourceType": "Condition", "id": "c2",
             "subject": {"identifier": {"system": "urn:his:mrn", "value": unlinked["mrn"]}},
             "recordedDate": "2025-01-01", "code": {"text": "Hypertension"}},
        ]
        plan = preview(client, admin, bundle("SPH-000000", *resources, extra_patients=[endod])).json()
        assert [i["patient"] for i in plan["items"]] == [f"Almaz Tefera ({linked['mrn']})"]
        assert plan["skipped"][0]["reason"] == f"Not Linked ({unlinked['mrn']}) is not linked to Endod"

    @pytest.mark.parametrize("data,message", [
        (b"not json", "not valid JSON"),
        (b'{"resourceType": "Patient"}', "not a FHIR Bundle"),
        (json.dumps({"resourceType": "Bundle", "entry": [{}] * 501}).encode(), "at most 500"),
    ])
    def test_unusable_files(self, client, admin, data, message):
        resp = preview(client, admin, data)
        assert resp.status_code == 400 and message in resp.json()["error"]

    def test_size_limit(self, client, admin):
        from app import imports

        resp = preview(client, admin, b"{" + b" " * imports.MAX_IMPORT_BYTES + b"}")
        assert resp.status_code == 413

    def test_who_imports(self, client, hospital):
        for role in ("doctor", "nurse", "reception", "pharmacist"):
            resp = preview(client, staff(client, hospital, role, f"{role}-i"), bundle("SPH-000001"))
            assert resp.status_code == 403, role

    def test_another_hospitals_preview_cannot_be_confirmed(self, client, admin, linked):
        from conftest import make_hospital

        plan = preview(client, admin, bundle(linked["mrn"], RESOURCES[0])).json()
        stranger = staff(client, make_hospital(code="BLH", name="Black Lion"), "admin", "admin-blh")
        assert client.post(f"/imports/{plan['import_id']}/confirm", headers=stranger).status_code == 404


class TestCsvImport:
    def test_template_and_rows(self, client, admin, linked, bus):
        template = client.get("/imports/template.csv", headers=admin)
        assert template.status_code == 200 and template.text.startswith("mrn,endod_id,category,title,occurred_at")
        header = template.text.strip()
        rows = [
            f"{linked['mrn']},,diagnosis,Hypertension,2025-01-05,Dr. Hana,Essential hypertension,I10,chronic"
            + "," * 19,
            ",DE482731,lab_result,Malaria RDT,2025-01-05T10:00:00+03:00,,,,,,,,,,,Malaria RDT,positive,,,"
            "high,blood,,,,,,,",
            f"{linked['mrn']},,prescription,,2025-01-05,,,,,Amoxicillin,500 mg,oral,three times daily,7 days,21"
            + "," * 13,
            f"{linked['mrn']},,visit_note,OPD,2025-01-05,,,,,,,,,,,,,,,,,,,,,Cough,Rest,",
            f"{linked['mrn']},,astrology,Stars,2025-01-05" + "," * 23,
            f"SPH-999999,,diagnosis,Asthma,2025-01-05,,Asthma" + "," * 21,
            f"{linked['mrn']},,diagnosis,Later,2999-01-01,,Later" + "," * 21,
        ]
        data = (header + "\n" + "\n".join(rows) + "\n").encode()
        plan = preview(client, admin, data, "export.csv", "text/csv").json()
        assert plan["format"] == "csv"
        assert [(i["what"], i["category"], i["title"]) for i in plan["items"]] == [
            ("row 2", "diagnosis", "Hypertension"), ("row 3", "lab_result", "Malaria RDT"),
            ("row 4", "prescription", "Prescription: Amoxicillin"), ("row 5", "visit_note", "OPD")]
        assert [(s["what"], s["reason"]) for s in plan["skipped"]] == [
            ("row 6", "category must be one of diagnosis, prescription, lab_result, imaging, visit_note"),
            ("row 7", "no patient with hospital number SPH-999999"),
            ("row 8", "the date is in the future")]
        client.post(f"/imports/{plan['import_id']}/confirm", headers=admin)
        published = {e["category"]: e for e in events(bus, "record.published")}
        assert published["diagnosis"]["details"] == {"condition": "Essential hypertension", "code": "I10",
                                                     "status": "chronic", "notes": None}
        assert published["diagnosis"]["recorded_by"] == "Dr. Hana"
        assert published["lab_result"]["details"]["items"][0]["flag"] == "high"
        assert published["prescription"]["details"]["items"][0]["quantity"] == "21"
        assert published["visit_note"]["details"]["complaint"] == "Cough"

    def test_a_csv_without_the_needed_columns(self, client, admin):
        resp = preview(client, admin, b"name,date\nAlmaz,2025-01-01\n", "x.csv", "text/csv")
        assert resp.status_code == 400 and "header" in resp.json()["error"]

    def test_the_documented_template_matches(self):
        from pathlib import Path

        from app import imports

        root = Path(__file__).resolve().parents[2]
        doc = (root / "docs" / "imports.md").read_text(encoding="utf-8")
        assert imports.template().strip() in doc
        public = root / "frontend-hospital-portal" / "public" / "import-template.csv"
        assert public.read_text(encoding="utf-8").splitlines()[0] == imports.template().strip()


def test_a_shared_file_name_cannot_break_the_header():
    from app import files

    header = files.content_disposition('lab\r\nSet-Cookie: a=b"\.pdf')
    assert "\r" not in header and "\n" not in header
    assert header.startswith('inline; filename="labSet-Cookie: a=b.pdf"; filename*=UTF-8\'\'')
