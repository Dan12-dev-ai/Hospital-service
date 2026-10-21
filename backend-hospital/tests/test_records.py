"""Clinical records, their files, visits and follow-ups (docs/history-events.md, sections 2 and 3)."""

import hashlib
from datetime import timedelta
from pathlib import Path

import pytest

from history_support import (  # noqa: F401  (fixtures)
    EXE, JPEG, PDF, PLATFORM_KEY, PNG, WEBP, bus, events, link_directly, platform_key, register, staff, today,
    upload,
)

DIAGNOSIS = {"category": "diagnosis", "title": "Malaria", "details": {
    "condition": "Plasmodium falciparum malaria", "code": "B50.9", "status": "active", "notes": "RDT positive",
    "unknown_key": "dropped"}}


@pytest.fixture
def doctor(client, hospital):
    return staff(client, hospital, "doctor")


@pytest.fixture
def desk(client, hospital):
    return staff(client, hospital, "reception")


@pytest.fixture
def patient(client, desk):
    return register(client, desk)


@pytest.fixture
def linked(patient):
    link_directly(patient["id"], "DE482731")
    return patient


def add(client, headers, patient_id, body=DIAGNOSIS):
    return client.post(f"/patients/{patient_id}/records", headers=headers, json=body)


class TestRecords:
    def test_published_only_for_linked_patients(self, client, doctor, patient, bus, hospital):
        resp = add(client, doctor, patient["id"])
        assert resp.status_code == 201, resp.text
        assert resp.json()["published"] is False and resp.json()["details"]["status"] == "active"
        assert "unknown_key" not in resp.json()["details"]
        assert events(bus, "record.published") == []

    def test_the_published_event_follows_the_contract(self, client, doctor, linked, bus, hospital):
        file_id = upload(client, doctor, linked["id"]).json()["id"]
        body = {**DIAGNOSIS, "occurred_at": "2026-10-20T09:30:00+03:00", "file_ids": [file_id]}
        record = add(client, doctor, linked["id"], body).json()
        assert record["published"] is True
        [event] = events(bus, "record.published")
        assert set(event) == {"record_id", "version", "hospital_id", "hospital_name", "dedan_id", "visit_id",
                              "category", "title", "details", "occurred_at", "recorded_by", "source", "files"}
        assert event["record_id"] == record["id"] and len(record["id"]) == 32
        assert event["version"] == 1 and event["dedan_id"] == "DE482731" and event["hospital_id"] == hospital
        assert event["hospital_name"] == "St. Paul's Millennium Medical Center"
        assert event["occurred_at"] == "2026-10-20T06:30:00+00:00"
        assert event["source"] == "portal" and event["recorded_by"] == "Doctor"
        assert event["details"] == {"condition": "Plasmodium falciparum malaria", "code": "B50.9",
                                    "status": "active", "notes": "RDT positive"}
        assert event["files"] == [{"file_id": file_id, "filename": "report.pdf", "content_type": "application/pdf",
                                   "size": len(PDF), "sha256": hashlib.sha256(PDF).hexdigest()}]

    def test_a_correction_is_a_higher_version(self, client, doctor, linked, bus):
        record = add(client, doctor, linked["id"]).json()
        resp = client.patch(f"/records/{record['id']}", headers=doctor, json={
            "details": {**DIAGNOSIS["details"], "status": "resolved"}})
        assert resp.status_code == 200 and resp.json()["version"] == 2
        versions = [(e["record_id"], e["version"], e["details"]["status"]) for e in events(bus, "record.published")]
        assert versions == [(record["id"], 1, "active"), (record["id"], 2, "resolved")]
        assert client.patch(f"/records/{record['id']}", headers=doctor, json={}).status_code == 400

    def test_retraction(self, client, doctor, linked, bus, hospital):
        record = add(client, doctor, linked["id"]).json()
        resp = client.post(f"/records/{record['id']}/retract", headers=doctor, json={"reason": "Wrong patient"})
        assert resp.status_code == 200 and resp.json()["retracted"] is True and resp.json()["published"] is False
        assert events(bus, "record.retracted") == [{"record_id": record["id"], "hospital_id": hospital,
                                                    "dedan_id": "DE482731", "reason": "Wrong patient"}]
        assert client.post(f"/records/{record['id']}/retract", headers=doctor,
                           json={"reason": "Again"}).status_code == 409
        assert client.patch(f"/records/{record['id']}", headers=doctor,
                            json={"title": "Fixed"}).status_code == 409
        # Retracting an unpublished record tells Endod nothing.
        link_directly(linked["id"], None)
        other = add(client, doctor, linked["id"]).json()
        client.post(f"/records/{other['id']}/retract", headers=doctor, json={"reason": "Typo"})
        assert len(events(bus, "record.retracted")) == 1

    def test_relinking_to_another_account_moves_the_record(self, client, doctor, linked, bus):
        record = add(client, doctor, linked["id"]).json()
        link_directly(linked["id"], "DE111111")
        client.patch(f"/records/{record['id']}", headers=doctor, json={"title": "Malaria (corrected)"})
        assert events(bus, "record.retracted")[0]["dedan_id"] == "DE482731"
        assert events(bus, "record.published")[-1]["dedan_id"] == "DE111111"

    @pytest.mark.parametrize("body", [
        {"category": "astrology", "title": "x x", "details": {}},
        {"category": "diagnosis", "title": "No condition", "details": {}},
        {"category": "diagnosis", "title": "Bad status", "details": {"condition": "x", "status": "maybe"}},
        {"category": "lab_result", "title": "Bad flag", "details": {"items": [{"test": "Hb", "flag": "weird"}]}},
        {"category": "lab_result", "title": "No items", "details": {"items": []}},
        {"category": "prescription", "title": "No drug", "details": {"items": [{"dose": "500 mg"}]}},
        {"category": "visit_note", "title": "Empty note", "details": {"vitals": {}}},
        {"category": "imaging", "title": "No modality", "details": {"findings": "x"}},
        {"category": "document", "title": "No file", "details": {"description": "Referral"}},
        {**DIAGNOSIS, "occurred_at": "2999-01-01T00:00:00+00:00"},
        {**DIAGNOSIS, "occurred_at": "2026-01-01T00:00:00"},  # no offset
    ])
    def test_invalid_records(self, client, doctor, patient, body):
        assert add(client, doctor, patient["id"], body).status_code in (400, 422)

    def test_structured_categories(self, client, doctor, hospital, patient):
        nurse = staff(client, hospital, "nurse")
        bodies = [
            {"category": "prescription", "title": "Coartem", "details": {"items": [
                {"drug": "Artemether/lumefantrine", "dose": "4 tablets", "route": "oral", "frequency": "twice daily",
                 "duration": "3 days", "quantity": 24}]}},
            {"category": "lab_result", "title": "CBC", "details": {"specimen": "blood", "items": [
                {"test": "Hemoglobin", "value": 9.1, "unit": "g/dL", "reference_range": "12-16", "flag": "low"}]}},
            {"category": "imaging", "title": "Chest X-ray", "details": {"modality": "X-ray", "body_part": "chest",
                                                                        "impression": "Normal"}},
            {"category": "visit_note", "title": "OPD visit", "details": {"complaint": "Fever",
                                                                         "vitals": {"bp": "120/80", "temp": 38.5}}},
        ]
        for body in bodies:
            resp = add(client, nurse, patient["id"], body)
            assert resp.status_code == 201, resp.text
        records = client.get(f"/patients/{patient['id']}/records", headers=doctor).json()["items"]
        lab = next(r for r in records if r["category"] == "lab_result")
        assert lab["details"]["items"][0]["value"] == "9.1"  # numbers are kept as text
        note = next(r for r in records if r["category"] == "visit_note")
        assert note["details"]["vitals"] == {"bp": "120/80", "pulse": None, "temp": "38.5", "weight": None,
                                             "height": None, "spo2": None}


class TestRoles:
    def test_who_writes_what(self, client, hospital, patient, doctor):
        records_clerk = staff(client, hospital, "records")
        admin = staff(client, hospital, "admin", "boss")
        pharmacist = staff(client, hospital, "pharmacist")
        assert add(client, records_clerk, patient["id"]).status_code == 403  # not a diagnosis
        assert add(client, admin, patient["id"]).status_code == 403
        assert add(client, pharmacist, patient["id"]).status_code == 403
        for who in (records_clerk, admin):
            file_id = upload(client, who, patient["id"]).json()["id"]
            resp = add(client, who, patient["id"], {"category": "document", "title": "Referral letter",
                                                    "details": {"description": "From the health centre"},
                                                    "file_ids": [file_id]})
            assert resp.status_code == 201, resp.text
            lab = add(client, who, patient["id"], {"category": "lab_result", "title": "Glucose",
                                                   "details": {"items": [{"test": "Glucose", "value": "5.4"}]}})
            assert lab.status_code == 201
        # Records staff cannot retract a doctor's diagnosis.
        record = add(client, doctor, patient["id"]).json()
        assert client.post(f"/records/{record['id']}/retract", headers=records_clerk,
                           json={"reason": "Not mine"}).status_code == 403

    def test_who_reads_clinical_details(self, client, hospital, patient, doctor):
        record = add(client, doctor, patient["id"]).json()
        file_id = upload(client, doctor, patient["id"]).json()["id"]
        add(client, doctor, patient["id"], {**DIAGNOSIS, "title": "With file", "file_ids": [file_id]})
        file_record = next(r for r in client.get(f"/patients/{patient['id']}/records", headers=doctor).json()["items"]
                           if r["files"])
        for role, allowed in (("reception", False), ("billing", False), ("pharmacist", True), ("records", True),
                              ("nurse", True), ("admin", True)):
            headers = staff(client, hospital, role, f"{role}-reader")
            listing = client.get(f"/patients/{patient['id']}/records", headers=headers)
            assert (listing.status_code == 200) is allowed, role
            download = client.get(f"/records/{file_record['id']}/files/{file_id}", headers=headers)
            assert (download.status_code == 200) is allowed, role
            assert client.get(f"/patients/{patient['id']}/visits", headers=headers).status_code == \
                (200 if allowed else 403)
        assert record["id"]

    def test_other_hospitals_see_nothing(self, client, doctor, patient):
        from conftest import make_hospital

        record = add(client, doctor, patient["id"]).json()
        other = make_hospital(code="BLH", name="Black Lion")
        stranger = staff(client, other, "doctor", "doc-blh")
        assert client.get(f"/patients/{patient['id']}/records", headers=stranger).status_code == 404
        assert add(client, stranger, patient["id"]).status_code == 404
        assert client.patch(f"/records/{record['id']}", headers=stranger, json={"title": "Mine now"}).status_code == 404
        assert client.post(f"/records/{record['id']}/retract", headers=stranger,
                           json={"reason": "Gone"}).status_code == 404
        assert upload(client, stranger, patient["id"]).status_code == 404


class TestFiles:
    @pytest.mark.parametrize("data,name,content_type", [
        (PDF, "lab.pdf", "application/pdf"), (PNG, "scan.png", "image/png"), (JPEG, "photo.JPG", "image/jpeg"),
        (WEBP, "x-ray.webp", "image/webp"), (PDF, "no-extension", "application/pdf"),
    ])
    def test_allowed_files_are_recognised_by_content(self, client, doctor, patient, data, name, content_type):
        resp = upload(client, doctor, patient["id"], data, name)
        assert resp.status_code == 201, resp.text
        assert resp.json()["content_type"] == content_type
        assert resp.json()["sha256"] == hashlib.sha256(data).hexdigest() and resp.json()["size"] == len(data)

    @pytest.mark.parametrize("data,name,status", [
        (EXE, "report.pdf", 415),  # a program named like a PDF
        (b"<html><script>alert(1)</script>", "page.png", 415),
        (PDF, "report.png", 400),  # a PDF named like an image
        (PDF, "report.exe", 400),
        (b"", "empty.pdf", 400),
    ])
    def test_other_files_are_refused(self, client, doctor, patient, data, name, status, tmp_path):
        assert upload(client, doctor, patient["id"], data, name).status_code == status
        stored = [p for p in (tmp_path / "files").rglob("*") if p.is_file()]
        assert stored == []  # nothing left behind

    def test_size_limit(self, client, doctor, patient, tmp_path):
        from app import files

        big = PDF + b"0" * (files.MAX_FILE_BYTES - len(PDF) + 1)
        assert upload(client, doctor, patient["id"], big).status_code == 413
        # Also when the declared length lies (streamed check).
        resp = client.post(f"/patients/{patient['id']}/uploads", headers={**doctor, "X-Filename": "a.pdf"},
                           content=iter([PDF, b"0" * files.MAX_FILE_BYTES]))
        assert resp.status_code == 413
        assert [p for p in (tmp_path / "files").rglob("*") if p.is_file()] == []

    def test_names_never_reach_the_disk(self, client, doctor, patient, tmp_path, hospital):
        resp = upload(client, doctor, patient["id"], PDF, "../../../etc/passwd.pdf")
        assert resp.status_code == 201 and resp.json()["filename"] == "passwd.pdf"
        resp = upload(client, doctor, patient["id"], PDF, '..\\..\\x"<evil>.pdf')
        assert resp.json()["filename"] == "xevil.pdf"
        stored = sorted(p.relative_to(tmp_path / "files").as_posix()
                        for p in (tmp_path / "files").rglob("*") if p.is_file())
        assert len(stored) == 2 and all(s.startswith(f"{hospital}/") for s in stored)
        assert all(len(Path(s).name) == 32 for s in stored)

    def test_paths_are_built_from_ids_only(self, tmp_path, monkeypatch):
        from app import files

        monkeypatch.setenv("HOSPITAL_FILES_DIR", str(tmp_path))
        for bad in ("../" + "a" * 29, "A" * 32, "a" * 31, "a" * 31 + "/", "..", ""):
            with pytest.raises(files.FileRejected):
                files.path_for("a" * 32, bad)
            with pytest.raises(files.FileRejected):
                files.path_for(bad, "a" * 32)

    def test_attaching(self, client, doctor, hospital, patient, desk):
        other_patient = register(client, desk, name="Other Patient", phone="0922000111")
        nurse = staff(client, hospital, "nurse")
        nurses_file = upload(client, nurse, patient["id"]).json()["id"]
        wrong_patient = upload(client, doctor, other_patient["id"]).json()["id"]
        for ids in ([nurses_file], [wrong_patient], ["f" * 32]):
            assert add(client, doctor, patient["id"], {**DIAGNOSIS, "file_ids": ids}).status_code == 400
        ten = [upload(client, doctor, patient["id"]).json()["id"] for _ in range(10)]
        record = add(client, doctor, patient["id"], {**DIAGNOSIS, "file_ids": ten}).json()
        assert len(record["files"]) == 10
        eleventh = upload(client, doctor, patient["id"]).json()["id"]
        assert client.patch(f"/records/{record['id']}", headers=doctor,
                            json={"add_file_ids": [eleventh]}).status_code == 400
        # A file attached once cannot be attached again.
        assert add(client, doctor, patient["id"], {**DIAGNOSIS, "file_ids": [ten[0]]}).status_code == 400
        assert add(client, doctor, patient["id"], {**DIAGNOSIS, "file_ids": [eleventh] * 11}).status_code == 422

    def test_download(self, client, doctor, patient):
        file_id = upload(client, doctor, patient["id"], PNG, "scan.png").json()["id"]
        record = add(client, doctor, patient["id"], {**DIAGNOSIS, "file_ids": [file_id]}).json()
        resp = client.get(f"/records/{record['id']}/files/{file_id}", headers=doctor)
        assert resp.status_code == 200 and resp.content == PNG
        assert resp.headers["content-type"] == "image/png"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert client.get(f"/records/{record['id']}/files/{'f' * 32}", headers=doctor).status_code == 404
        # An upload not attached to this record is not reachable through it.
        loose = upload(client, doctor, patient["id"]).json()["id"]
        assert client.get(f"/records/{record['id']}/files/{loose}", headers=doctor).status_code == 404

    def test_abandoned_uploads_are_cleaned_up(self, client, doctor, patient, tmp_path):
        from sqlalchemy import update

        from app import chores
        from app.db import session_scope, utcnow
        from app.models import RecordFile

        upload(client, doctor, patient["id"])
        with session_scope() as session:
            session.execute(update(RecordFile).values(created_at=utcnow() - timedelta(days=3)))
        assert chores.run() == 1
        assert [p for p in (tmp_path / "files").rglob("*") if p.is_file()] == []


class TestPlatformDownload:
    def _published(self, client, doctor, linked):
        file_id = upload(client, doctor, linked["id"]).json()["id"]
        record = add(client, doctor, linked["id"], {**DIAGNOSIS, "file_ids": [file_id]}).json()
        return record["id"], file_id

    def test_needs_the_platform_key(self, client, doctor, linked, monkeypatch):
        record_id, file_id = self._published(client, doctor, linked)
        url = f"/platform/records/{record_id}/files/{file_id}"
        assert client.get(url).status_code == 401
        assert client.get(url, headers={"X-Platform-Key": "wrong"}).status_code == 401
        assert client.get(url, headers=doctor).status_code == 401  # a staff session is not the key
        resp = client.get(url, headers={"X-Platform-Key": PLATFORM_KEY})
        assert resp.status_code == 200 and resp.content == PDF
        assert resp.headers["x-sha256"] == hashlib.sha256(PDF).hexdigest()
        monkeypatch.delenv("HOSPITAL_PLATFORM_ADMIN_KEY")
        assert client.get(url, headers={"X-Platform-Key": PLATFORM_KEY}).status_code == 404

    def test_only_published_records(self, client, doctor, patient, linked):
        key = {"X-Platform-Key": PLATFORM_KEY}
        record_id, file_id = self._published(client, doctor, linked)
        client.post(f"/records/{record_id}/retract", headers=doctor, json={"reason": "Wrong patient"})
        assert client.get(f"/platform/records/{record_id}/files/{file_id}", headers=key).status_code == 404
        link_directly(linked["id"], None)
        file_id = upload(client, doctor, linked["id"]).json()["id"]
        record = add(client, doctor, linked["id"], {**DIAGNOSIS, "file_ids": [file_id]}).json()
        assert client.get(f"/platform/records/{record['id']}/files/{file_id}", headers=key).status_code == 404
        assert client.get(f"/platform/records/{record['id']}/files/..%2F..%2Fetc", headers=key).status_code == 404


class TestVisits:
    def test_follow_up_set_moved_and_cancelled(self, client, doctor, linked, bus, hospital):
        on = today() + timedelta(days=14)
        resp = client.post(f"/patients/{linked['id']}/visits", headers=doctor, json={
            "follow_up_on": on.isoformat(), "follow_up_note": "Review the lab results"})
        assert resp.status_code == 201, resp.text
        visit = resp.json()
        assert visit["doctor"]["full_name"] == "Doctor" and visit["follow_up_sent"] is True
        later = on + timedelta(days=7)
        client.patch(f"/visits/{visit['id']}", headers=doctor, json={"follow_up_on": later.isoformat()})
        client.patch(f"/visits/{visit['id']}", headers=doctor, json={"follow_up_on": None})
        sent = events(bus, "visit.follow_up")
        assert sent[0] == {"visit_id": visit["id"], "hospital_id": hospital,
                           "hospital_name": "St. Paul's Millennium Medical Center", "dedan_id": "DE482731",
                           "follow_up_on": on.isoformat(), "note": "Review the lab results",
                           "doctor_name": "Doctor", "cancelled": False}
        assert [(e["follow_up_on"], e["cancelled"]) for e in sent] == [
            (on.isoformat(), False), (later.isoformat(), False), (later.isoformat(), True)]
        assert client.patch(f"/visits/{visit['id']}", headers=doctor, json={"follow_up_on": None}).status_code == 400

    def test_records_belong_to_a_visit(self, client, doctor, linked, bus):
        visit = client.post(f"/patients/{linked['id']}/visits", headers=doctor, json={}).json()
        record = add(client, doctor, linked["id"], {**DIAGNOSIS, "visit_id": visit["id"]}).json()
        assert record["visit_id"] == visit["id"]
        assert events(bus, "record.published")[0]["visit_id"] == visit["id"]
        assert add(client, doctor, linked["id"], {**DIAGNOSIS, "visit_id": "f" * 32}).status_code == 400

    def test_follow_up_rules(self, client, doctor, hospital, patient, bus):
        nurse = staff(client, hospital, "nurse")
        tomorrow = (today() + timedelta(days=1)).isoformat()
        assert client.post(f"/patients/{patient['id']}/visits", headers=nurse,
                           json={"follow_up_on": tomorrow}).status_code == 403
        visit = client.post(f"/patients/{patient['id']}/visits", headers=nurse, json={}).json()
        assert client.patch(f"/visits/{visit['id']}", headers=nurse, json={"follow_up_on": tomorrow}).status_code == 403
        for bad in (today().isoformat(), (today() + timedelta(days=800)).isoformat()):
            assert client.patch(f"/visits/{visit['id']}", headers=doctor, json={"follow_up_on": bad}).status_code == 400
        assert client.post(f"/patients/{patient['id']}/visits", headers=staff(client, hospital, "reception", "desk2"),
                           json={}).status_code == 403
        # Not linked: kept here, nothing sent until the patient is linked.
        resp = client.patch(f"/visits/{visit['id']}", headers=doctor, json={"follow_up_on": tomorrow})
        assert resp.json()["follow_up_sent"] is False and events(bus, "visit.follow_up") == []

    def test_a_follow_up_is_sent_when_the_patient_is_linked(self, client, doctor, patient, bus):
        from app import linking, records
        from app.db import session_scope
        from app.models import Patient

        on = (today() + timedelta(days=3)).isoformat()
        client.post(f"/patients/{patient['id']}/visits", headers=doctor, json={"follow_up_on": on})
        with session_scope() as session:
            row = session.get(Patient, patient["id"])
            linking.link(session, row, "DE482731", records.hospital_today(session, row.hospital_id))
        [sent] = events(bus, "visit.follow_up")
        assert sent["follow_up_on"] == on and sent["dedan_id"] == "DE482731" and sent["cancelled"] is False


class TestCorrectionsWhileUnlinked:
    def test_a_correction_made_while_unlinked_is_sent_on_relinking(self, client, doctor, desk, linked, bus):
        from app import records
        from app.db import session_scope
        from app.linking import link
        from app.models import Patient

        record = add(client, doctor, linked["id"]).json()
        assert [e["version"] for e in events(bus, "record.published")] == [1]
        assert client.delete(f"/patients/{linked['id']}/link", headers=desk).status_code == 200
        fixed = client.patch(f"/records/{record['id']}", headers=doctor, json={"title": "Malaria (corrected)"})
        assert fixed.status_code == 200 and fixed.json()["version"] == 2
        assert fixed.json()["published"] is False  # Endod still has version 1
        assert len(events(bus, "record.published")) == 1  # nothing sent while unlinked

        with session_scope() as session:  # Endod confirms the same account again
            link(session, session.get(Patient, linked["id"]), "DE482731", today())
        sent = events(bus, "record.published")
        assert [(e["version"], e["title"], e["dedan_id"]) for e in sent] == [
            (1, "Malaria", "DE482731"), (2, "Malaria (corrected)", "DE482731")]
        assert events(bus, "record.retracted") == []  # same account: nothing to take back
        listed = client.get(f"/patients/{linked['id']}/records", headers=doctor).json()["items"][0]
        assert listed["published"] is True and listed["published_version"] == 2

        # Nothing more to send: Endod has the current version.
        with session_scope() as session:
            assert records.publish_history(session, session.get(Patient, linked["id"]), today()) == 0

    def test_relinking_to_another_account_moves_the_record(self, client, doctor, desk, linked, bus):
        from app.db import session_scope
        from app.linking import link
        from app.models import Patient

        record = add(client, doctor, linked["id"]).json()
        client.delete(f"/patients/{linked['id']}/link", headers=desk)
        with session_scope() as session:
            link(session, session.get(Patient, linked["id"]), "DE111111", today())
        [retracted] = events(bus, "record.retracted")
        assert retracted["record_id"] == record["id"] and retracted["dedan_id"] == "DE482731"
        assert [e["dedan_id"] for e in events(bus, "record.published")] == ["DE482731", "DE111111"]
