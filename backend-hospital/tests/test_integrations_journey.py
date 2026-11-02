"""The patient journey through the integration API (docs/integrations.md,
sections 4 to 9): patients, links, booking decisions, follow-ups,
prescriptions, read-back, the queue. Each endpoint uses the portal's rules,
events and audit; test connections write nothing; another hospital's data is
never found."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from conftest import make_hospital, make_staff
from test_integrations import (  # noqa: F401  (fixtures)
    API, MRN_SYSTEM, admin, book, client, connected, count, entry, fresh_limits, get_token, make_patient,
    observation, post_bundle,
)

from app import dispensing, linking
from app.db import platform_session
from app.integrations import webhooks
from app.models import (
    AuditEvent, Booking, ClinicalRecord, Hospital, IntegrationIdempotency, OutboxEvent, Patient, PatientLinkRequest,
    QueueEntry, Visit, WebhookDelivery,
)

JOURNEY = ["patients.read", "patients.write", "bookings.read", "bookings.write", "followups.write",
           "prescriptions.read", "queue.write", "webhooks", "records.labs.write", "records.prescriptions.write"]
HOOK = "https://hooks.example.com/endod"


@pytest.fixture
def live(client, admin):
    return connected(client, admin, scopes=JOURNEY, webhook_url=HOOK, name="EMR")


@pytest.fixture
def auth(client, live):
    return get_token(client, live)


@pytest.fixture
def test_auth(client, admin):
    return get_token(client, connected(client, admin, scopes=JOURNEY, mode="test", webhook_url=HOOK,
                                       name="EMR test"))


@pytest.fixture
def doctor(hospital):
    return make_staff(hospital, "abebe@sph.example", role="doctor")


def outbox(kind=None):
    with platform_session() as session:
        rows = session.scalars(select(OutboxEvent).order_by(OutboxEvent.created_at, OutboxEvent.id)).all()
        return [(r.type, json.loads(r.payload)) for r in rows if kind is None or r.type == kind]


def audits(action):
    with platform_session() as session:
        return [json.loads(r.detail or "{}") | {"_target": r.target_id, "_actor": r.actor_id}
                for r in session.scalars(select(AuditEvent).where(AuditEvent.action == action))]


def deliveries(event_type=None):
    with platform_session() as session:
        rows = session.scalars(select(WebhookDelivery).order_by(WebhookDelivery.created_at)).all()
        return [r.event_type for r in rows if event_type is None or r.event_type == event_type]


def sent_events(monkeypatch):
    sent = []

    def fake_post(url, headers, body, deadline=None):
        sent.append(json.loads(body))
        return webhooks.Sent(True, 200, None)

    monkeypatch.setattr(webhooks, "post", fake_post)
    return sent


def writes():
    """Everything a test connection must never write."""
    models = (Patient, PatientLinkRequest, Booking, Visit, ClinicalRecord, QueueEntry, OutboxEvent, AuditEvent,
              WebhookDelivery)
    return {m.__name__: count(m) for m in models}


def register(client, auth, **body):
    payload = {"full_name": "Almaz Tefera", "sex": "female", "date_of_birth": "1990-04-12",
               "phone": "+251911234567", **body}
    return client.post(f"{API}/patients", headers=auth, json=payload)


# --- patients ---------------------------------------------------------------------------------------------

class TestPatients:
    def test_register_issues_the_hospital_number_and_audits(self, client, auth, live):
        resp = register(client, auth, claimed_endod_id="de-482731")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["mrn"] == "SPH-000001" and body["link"] == {
            "status": "not_linked", "endod_id": None, "claimed_endod_id": "DE482731", "request": None}
        [row] = audits("patient_registered")
        assert row["client_id"] == live["connection"]["client_id"] and row["via"] == "integration"
        assert row["_actor"] is None and row["mrn"] == "SPH-000001"
        assert client.get(f"{API}/patients/sph-000001", headers=auth).json()["id"] == body["id"]

    def test_same_rules_as_the_portal(self, client, auth):
        assert register(client, auth).status_code == 201
        duplicate = register(client, auth)
        assert duplicate.status_code == 409 and "SPH-000001" in duplicate.json()["issue"][0]["diagnostics"]
        assert register(client, auth, confirm_duplicate=True).json()["mrn"] == "SPH-000002"
        assert register(client, auth, sex="other").status_code == 400
        future = (date.today() + timedelta(days=3)).isoformat()
        assert register(client, auth, date_of_birth=future).status_code == 400
        bad = register(client, auth, age_years=40)  # both a date of birth and an age
        assert bad.status_code == 422 and bad.json()["resourceType"] == "OperationOutcome"

    def test_idempotency_key(self, client, auth):
        key = {**auth, "Idempotency-Key": "emr-reg-0001"}
        first = client.post(f"{API}/patients", headers=key, json={"full_name": "Almaz Tefera", "sex": "female"})
        again = client.post(f"{API}/patients", headers=key, json={"full_name": "Almaz Tefera", "sex": "female"})
        assert again.status_code == 201 and again.json() == first.json()
        assert again.headers.get("idempotent-replayed") == "true" and count(Patient) == 1
        other = client.post(f"{API}/patients", headers=key, json={"full_name": "Kebede Alemu", "sex": "male"})
        assert other.status_code == 422 and "Idempotency-Key" in other.json()["issue"][0]["diagnostics"]
        assert count(Patient) == 1

    def test_scopes(self, client, admin):
        reader = get_token(client, connected(client, admin, scopes=["patients.read"], name="Reader"))
        resp = register(client, reader)
        assert resp.status_code == 403 and "insufficient_scope" in resp.headers["www-authenticate"]
        writer = get_token(client, connected(client, admin, scopes=["patients.write"], name="Writer"))
        assert register(client, writer).status_code == 201
        assert client.get(f"{API}/patients/SPH-000001", headers=writer).status_code == 403
        assert client.get(f"{API}/patients/SPH-000001", headers=reader).status_code == 200
        assert client.get(f"{API}/patients/SPH-000001").status_code == 401

    def test_another_hospitals_patient_is_not_found(self, client, auth):
        other = make_hospital(code="BET", name="Bethel Hospital")
        make_patient(other, mrn="BET-000001")
        make_patient(other, mrn="SPH-000009")  # even with this hospital's prefix
        for mrn in ("BET-000001", "SPH-000009"):
            assert client.get(f"{API}/patients/{mrn}", headers=auth).status_code == 404
            assert client.post(f"{API}/patients/{mrn}/link", headers=auth,
                               json={"endod_id": "DE482731", "phone": "+251911234567"}).status_code == 404

    def test_test_mode_writes_nothing_and_never_says_who_exists(self, client, test_auth, hospital):
        make_patient(hospital, mrn="SPH-000001", dedan_id="DE654321")
        before = writes()
        resp = register(client, test_auth)
        assert resp.status_code == 201 and resp.json()["sample"] and resp.json()["mrn"] == "TEST-000001"
        assert register(client, test_auth, sex="other").status_code == 400  # checked all the same
        real = client.get(f"{API}/patients/SPH-000001", headers=test_auth).json()
        made_up = client.get(f"{API}/patients/SPH-404404", headers=test_auth).json()
        strip = lambda p: {k: v for k, v in p.items() if k not in ("mrn", "created_at")}  # noqa: E731
        assert strip(real) == strip(made_up) and real["sample"] and "DE654321" not in json.dumps(real)
        linked = client.post(f"{API}/patients/SPH-000001/link", headers=test_auth,
                             json={"endod_id": "DE482731", "phone": "+251911234567"})
        assert linked.status_code == 202 and linked.json()["status"] == "pending"
        assert client.post(f"{API}/patients/SPH-000001/link", headers=test_auth,
                           json={"endod_id": "nope"}).status_code == 400
        assert client.delete(f"{API}/patients/SPH-000001/link", headers=test_auth).json()["sample"]
        assert writes() == before


# --- linking ------------------------------------------------------------------------------------------------

def link_requested():
    [(_, payload)] = outbox("patient.link_requested")[-1:]
    return payload


class TestLinking:
    def test_link_by_endod_id_and_phone_then_linked(self, client, auth, hospital, monkeypatch):
        sent = sent_events(monkeypatch)
        register(client, auth)
        resp = client.post(f"{API}/patients/SPH-000001/link", headers=auth,
                           json={"endod_id": "de-482731", "phone": "0911 234 567"})
        assert resp.status_code == 202, resp.text
        assert resp.json()["status"] == "pending" and resp.json()["request"]["method"] == "phone"
        request = link_requested()
        assert request["dedan_id"] == "DE482731" and request["phone"] == "+251911234567"
        assert request["card_signature"] is None
        [row] = audits("patient_link_requested")
        assert row["request_id"] == request["request_id"] and row["via"] == "integration"
        with platform_session() as session:
            linking.on_linked(session, {**{k: request[k] for k in ("request_id", "hospital_id", "patient_id",
                                                                   "dedan_id")}, "name": "Almaz Tefera"})
        assert client.get(f"{API}/patients/SPH-000001", headers=auth).json()["link"]["status"] == "linked"
        webhooks.deliver_due()
        [event] = [e for e in sent if e["type"] == "patient.linked"]
        assert event["data"] == {"patient_id": request["patient_id"], "mrn": "SPH-000001", "endod_id": "DE482731",
                                 "request_id": request["request_id"]}

    def test_by_health_card_and_refused(self, client, auth, monkeypatch):
        sent = sent_events(monkeypatch)
        register(client, auth)
        resp = client.post(f"{API}/patients/SPH-000001/link", headers=auth,
                           json={"card_url": "https://endod-health.com/card/DE482731?s=c2lnbmF0dXJlLTEyMw"})
        assert resp.status_code == 202 and resp.json()["request"]["method"] == "card"
        request = link_requested()
        assert request["card_signature"] == "c2lnbmF0dXJlLTEyMw" and request["phone"] is None
        with platform_session() as session:
            linking.on_refused(session, {**{k: request[k] for k in ("request_id", "hospital_id", "patient_id",
                                                                    "dedan_id")}, "reason": "not_verified"})
        link = client.get(f"{API}/patients/SPH-000001", headers=auth).json()["link"]
        assert link["status"] == "refused" and link["request"]["reason"] == "not_verified"
        webhooks.deliver_due()
        [event] = [e for e in sent if e["type"] == "patient.link_refused"]
        assert event["data"]["reason"] == "not_verified" and event["data"]["request_id"] == request["request_id"]
        assert event["data"]["mrn"] == "SPH-000001"

    def test_invalid_requests_and_unlink(self, client, auth, hospital, monkeypatch):
        sent = sent_events(monkeypatch)
        register(client, auth)
        for body in ({"endod_id": "DE482731"}, {"endod_id": "nope", "phone": "+251911234567"},
                     {"card_url": "https://evil.example.com/card/DE482731?s=abcdefghij"}):
            assert client.post(f"{API}/patients/SPH-000001/link", headers=auth, json=body).status_code == 400
        assert outbox("patient.link_requested") == []
        with platform_session() as session:
            session.scalar(select(Patient)).dedan_id = "DE482731"
        already = client.post(f"{API}/patients/SPH-000001/link", headers=auth,
                              json={"endod_id": "DE111111", "phone": "+251911234567"})
        assert already.status_code == 409
        resp = client.delete(f"{API}/patients/SPH-000001/link", headers=auth)
        assert resp.status_code == 200 and resp.json()["status"] == "not_linked"
        assert audits("patient_unlinked")[0]["via"] == "integration"
        webhooks.deliver_due()
        assert [e["type"] for e in sent] == ["patient.unlinked"]


# --- bookings ------------------------------------------------------------------------------------------------

@pytest.fixture
def video(hospital):
    with platform_session() as session:
        session.get(Hospital, hospital).video_enabled = True
    return book(hospital, mode="video")


class TestBookingDecisions:
    def test_approve_a_video_visit(self, client, auth, live, doctor, video):
        resp = client.post(f"{API}/bookings/{video}/approve", headers=auth, json={"doctor_id": doctor})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "confirmed" and body["doctor"] == {"id": doctor, "full_name": "Abebe"}
        [(_, event)] = outbox("appointment.confirmed")
        assert event["status"] == "confirmed" and event["meeting_room"] and event["doctor_name"] == "Abebe"
        [row] = audits("booking_confirmed")
        assert row["client_id"] == live["connection"]["client_id"] and row["_target"] == video
        assert deliveries("booking.confirmed") == ["booking.confirmed"]
        again = client.post(f"{API}/bookings/{video}/approve", headers=auth, json={"doctor_id": doctor})
        assert again.status_code == 409

    def test_unknown_doctor_or_not_a_video_visit(self, client, auth, hospital, video):
        assert client.post(f"{API}/bookings/{video}/approve", headers=auth,
                           json={"doctor_id": "nobody"}).status_code == 400
        in_person = book(hospital)
        nurse = make_staff(hospital, "nurse@sph.example", role="nurse")
        assert client.post(f"{API}/bookings/{in_person}/approve", headers=auth,
                           json={"doctor_id": nurse}).status_code == 400

    def test_decline_needs_a_reason_and_refunds(self, client, auth, video):
        assert client.post(f"{API}/bookings/{video}/decline", headers=auth, json={}).status_code == 422
        resp = client.post(f"{API}/bookings/{video}/decline", headers=auth, json={"reason": "Doctor away"})
        assert resp.status_code == 200 and resp.json()["status"] == "rejected"
        [(_, event)] = outbox("appointment.rejected")
        assert event["reason"] == "Doctor away"
        assert deliveries("booking.cancelled") == ["booking.cancelled"]

    def test_cancel_and_complete(self, client, auth, hospital):
        booking = book(hospital)
        resp = client.post(f"{API}/bookings/{booking}/cancel", headers=auth, json={"reason": "Ward closed"})
        assert resp.status_code == 200 and resp.json()["status"] == "cancelled"
        [(_, event)] = outbox("appointment.cancelled")
        assert event["by"] == "hospital" and event["reason"] == "Ward closed"
        assert client.post(f"{API}/bookings/{booking}/cancel", headers=auth,
                           json={"reason": "Again"}).status_code == 409
        later = book(hospital)
        early = client.post(f"{API}/bookings/{later}/complete", headers=auth)
        assert early.status_code == 409 and "before it starts" in early.json()["issue"][0]["diagnostics"]
        with platform_session() as session:
            session.get(Booking, later).scheduled_at = datetime.now(timezone.utc) - timedelta(hours=1)
        done = client.post(f"{API}/bookings/{later}/complete", headers={**auth, "Idempotency-Key": "c-1"})
        assert done.status_code == 200 and done.json()["status"] == "completed"
        replay = client.post(f"{API}/bookings/{later}/complete", headers={**auth, "Idempotency-Key": "c-1"})
        assert replay.json() == done.json() and replay.headers.get("idempotent-replayed") == "true"
        assert len(outbox("appointment.completed")) == 1

    def test_scopes_and_other_hospitals(self, client, admin, auth, hospital, video):
        reader = get_token(client, connected(client, admin, scopes=["bookings.read"], name="Reader"))
        resp = client.post(f"{API}/bookings/{video}/decline", headers=reader, json={"reason": "No"})
        assert resp.status_code == 403
        other = make_hospital(code="BET", name="Bethel Hospital")
        theirs = book(other)
        for action, body in (("cancel", {"reason": "No"}), ("complete", None), ("decline", {"reason": "No"})):
            assert client.post(f"{API}/bookings/{theirs}/{action}", headers=auth, json=body).status_code == 404
        assert client.get(f"{API}/bookings/{theirs}", headers=auth).status_code == 404

    def test_test_mode_tries_the_rules_on_sample_bookings(self, client, test_auth, doctor, video):
        before = writes()
        items = client.get(f"{API}/bookings", headers=test_auth).json()["items"]
        by_status = {(b["visit_mode"], b["status"]): b["id"] for b in items}
        awaiting = by_status[("video", "awaiting_doctor")]
        resp = client.post(f"{API}/bookings/{awaiting}/approve", headers=test_auth, json={"doctor_id": doctor})
        assert resp.status_code == 200 and resp.json()["status"] == "confirmed" and resp.json()["sample"]
        confirmed = [b for b in items if b["status"] == "confirmed"]
        assert client.post(f"{API}/bookings/{awaiting}/approve", headers=test_auth,
                           json={"doctor_id": "nobody"}).status_code == 400
        assert client.post(f"{API}/bookings/{confirmed[0]['id']}/decline", headers=test_auth,
                           json={"reason": "No"}).status_code == 409
        started = max(confirmed, key=lambda b: b["scheduled_at"] < datetime.now(timezone.utc).isoformat())
        assert client.post(f"{API}/bookings/{started['id']}/complete", headers=test_auth).json()["status"] \
            == "completed"
        assert client.post(f"{API}/bookings/{video}/cancel", headers=test_auth,
                           json={"reason": "No"}).status_code == 404  # real bookings are never seen
        assert writes() == before
        with platform_session() as session:
            assert session.get(Booking, video).status == "awaiting_doctor"


# --- follow-ups ----------------------------------------------------------------------------------------------

class TestFollowUps:
    def test_create_list_cancel(self, client, auth, hospital, doctor):
        make_patient(hospital, mrn="SPH-000001", dedan_id="DE482731")
        on = (date.today() + timedelta(days=14)).isoformat()
        resp = client.post(f"{API}/patients/SPH-000001/follow-ups", headers=auth,
                           json={"date": on, "note": "Review the blood film", "doctor_id": doctor})
        assert resp.status_code == 201, resp.text
        follow_up = resp.json()
        assert follow_up["status"] == "scheduled" and follow_up["sent_to_endod"] and follow_up["date"] == on
        [(_, event)] = outbox("visit.follow_up")
        assert event["dedan_id"] == "DE482731" and event["follow_up_on"] == on
        assert audits("visit_opened")[0]["via"] == "integration"
        listed = client.get(f"{API}/patients/SPH-000001/follow-ups", headers=auth).json()["items"]
        assert [f["id"] for f in listed] == [follow_up["id"]]
        cancelled = client.post(f"{API}/follow-ups/{follow_up['id']}/cancel", headers=auth)
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        assert outbox("visit.follow_up")[-1][1]["cancelled"] is True
        assert client.post(f"{API}/follow-ups/{follow_up['id']}/cancel", headers=auth).status_code == 400
        assert client.get(f"{API}/patients/SPH-000001/follow-ups", headers=auth).json()["items"] == []

    def test_rules_scopes_and_other_hospitals(self, client, admin, auth, hospital):
        make_patient(hospital, mrn="SPH-000001")
        today = date.today().isoformat()
        assert client.post(f"{API}/patients/SPH-000001/follow-ups", headers=auth,
                           json={"date": today}).status_code == 400
        far = (date.today() + timedelta(days=800)).isoformat()
        assert client.post(f"{API}/patients/SPH-000001/follow-ups", headers=auth,
                           json={"date": far}).status_code == 400
        reader = get_token(client, connected(client, admin, scopes=["patients.read"], name="Reader"))
        soon = (date.today() + timedelta(days=7)).isoformat()
        assert client.post(f"{API}/patients/SPH-000001/follow-ups", headers=reader,
                           json={"date": soon}).status_code == 403
        other = make_hospital(code="BET", name="Bethel Hospital")
        make_patient(other, mrn="BET-000001")
        assert client.post(f"{API}/patients/BET-000001/follow-ups", headers=auth,
                           json={"date": soon}).status_code == 404
        with platform_session() as session:
            theirs = Visit(hospital_id=other, patient_id=session.scalar(select(Patient.id).where(
                Patient.hospital_id == other)), follow_up_on=date.today() + timedelta(days=3))
            session.add(theirs)
            session.flush()
            visit_id = theirs.id
        assert client.post(f"{API}/follow-ups/{visit_id}/cancel", headers=auth).status_code == 404

    def test_test_mode(self, client, test_auth, hospital):
        make_patient(hospital, mrn="SPH-000001", dedan_id="DE482731")
        before = writes()
        soon = (date.today() + timedelta(days=7)).isoformat()
        resp = client.post(f"{API}/patients/SPH-000404/follow-ups", headers=test_auth, json={"date": soon})
        assert resp.status_code == 201 and resp.json()["sample"]
        assert client.post(f"{API}/patients/SPH-000001/follow-ups", headers=test_auth,
                           json={"date": date.today().isoformat()}).status_code == 400
        assert client.get(f"{API}/patients/SPH-000001/follow-ups", headers=test_auth).json()["items"][0]["sample"]
        assert client.post(f"{API}/follow-ups/sample-follow-up-1/cancel", headers=test_auth).status_code == 200
        assert writes() == before


# --- prescriptions and read-back -----------------------------------------------------------------------------

PRESCRIPTION = {
    "resourceType": "MedicationRequest", "id": "rx-0001", "status": "active", "intent": "order",
    "medicationCodeableConcept": {"text": "Amoxicillin 500 mg capsule"},
    "subject": {"identifier": {"system": MRN_SYSTEM, "value": "SPH-000001"}}, "authoredOn": "2026-10-01",
    "dosageInstruction": [{"text": "1 capsule three times a day"}],
    "dispenseRequest": {"quantity": {"value": 21, "unit": "capsules"}},
}


def their_record(category, title="Theirs"):
    """A record of another hospital's patient (sent through their own connection)."""
    other = make_hospital(code="BET", name="Bethel Hospital")
    patient_id = make_patient(other, mrn="BET-000001")
    with platform_session() as session:
        record = ClinicalRecord(hospital_id=other, patient_id=patient_id, category=category, title=title,
                                details=json.dumps({"items": [{"drug": "X", "quantity": "1"}]}),
                                occurred_at=datetime.now(timezone.utc), source="import", version=1)
        session.add(record)
        session.flush()
        return record.id


def send_prescription(client, auth):
    resp = client.post(f"{API}/fhir/MedicationRequest", headers={**auth, "Content-Type": "application/fhir+json"},
                       content=json.dumps(PRESCRIPTION))
    assert resp.status_code == 201, resp.text
    return resp.headers["location"].split("/")[1]


class TestPrescriptions:
    def test_dispensing_status_and_webhook(self, client, auth, hospital, monkeypatch):
        sent = sent_events(monkeypatch)
        make_patient(hospital, mrn="SPH-000001", dedan_id="DE482731")
        record_id = send_prescription(client, auth)
        first = client.get(f"{API}/prescriptions/{record_id}", headers=auth).json()
        assert first["status"] == "not_dispensed" and first["items"][0]["remaining"] == 21
        with platform_session() as session:
            dispensing.on_dispensed(session, {
                "record_id": record_id, "hospital_id": hospital, "dedan_id": "DE482731", "dispense_id": "dsp-1",
                "at": "2026-10-23T14:10:00+03:00", "pharmacy_name": "Kenema Pharmacy", "status": "open",
                "items": [{"item_index": 0, "amount": 14, "complete": False, "given_total": 14,
                           "status": "partly_given"}]})
        body = client.get(f"{API}/prescriptions/{record_id}", headers=auth).json()
        assert body["status"] == "partly"
        assert {k: body["items"][0][k] for k in ("status", "given_total", "remaining", "last_pharmacy")} == {
            "status": "partly_given", "given_total": 14, "remaining": 7, "last_pharmacy": "Kenema Pharmacy"}
        webhooks.deliver_due()
        [event] = [e for e in sent if e["type"] == "prescription.dispensed"]
        assert event["data"] == {"prescription_id": record_id, "dispense_id": "dsp-1", "dispense_status": "open",
                                 "dispensing_status": "partly", "dispensed_at": "2026-10-23T11:10:00+00:00",
                                 "patient": {"patient_id": event["data"]["patient"]["patient_id"],
                                             "mrn": "SPH-000001", "endod_id": "DE482731"}}
        assert "Amoxicillin" not in json.dumps(event) and "Kenema" not in json.dumps(event)

    def test_scopes_other_hospitals_and_test_mode(self, client, admin, auth, hospital, test_auth):
        make_patient(hospital, mrn="SPH-000001", dedan_id="DE482731")
        record_id = send_prescription(client, auth)
        labs = get_token(client, connected(client, admin, scopes=["records.labs.write"], name="Lab"))
        assert client.get(f"{API}/prescriptions/{record_id}", headers=labs).status_code == 403
        assert client.get(f"{API}/prescriptions/{their_record('prescription')}", headers=auth).status_code == 404
        assert client.get(f"{API}/prescriptions/{record_id}", headers=test_auth).status_code == 404
        assert client.get(f"{API}/prescriptions/sample-prescription-1", headers=test_auth).json()["sample"]


class TestReadBack:
    def test_by_record_id_and_own_id(self, client, auth, hospital):
        make_patient(hospital, mrn="SPH-000001")
        resp = post_bundle(client, auth, [entry(observation(rid="hb-1", version="1"), method="PUT")])
        record_id = resp.json()["entry"][0]["response"]["location"].split("/")[1]
        by_id = client.get(f"{API}/fhir/Observation/{record_id}", headers=auth)
        assert by_id.status_code == 200 and by_id.headers["content-type"].startswith("application/fhir+json")
        body = by_id.json()
        assert body["id"] == record_id and body["status"] == "final" and body["code"] == {"text": "Hemoglobin"}
        assert body["subject"]["identifier"] == {"system": MRN_SYSTEM, "value": "SPH-000001"}
        assert body["identifier"][0]["value"] == "hb-1" and body["meta"]["versionId"] == "1"
        assert client.get(f"{API}/fhir/Observation/hb-1", headers=auth).json()["id"] == record_id
        assert client.get(f"{API}/fhir/Condition/{record_id}", headers=auth).status_code == 403  # no such scope
        assert client.get(f"{API}/fhir/MedicationRequest/{record_id}", headers=auth).status_code == 404
        assert client.get(f"{API}/fhir/Patient/{record_id}", headers=auth).status_code == 400

    def test_other_hospitals_and_test_mode(self, client, auth, hospital, test_auth):
        make_patient(hospital, mrn="SPH-000001")
        resp = post_bundle(client, auth, [entry(observation())])
        record_id = resp.json()["entry"][0]["response"]["location"].split("/")[1]
        assert client.get(f"{API}/fhir/Observation/{record_id}", headers=test_auth).status_code == 404
        theirs = their_record("lab_result")
        assert client.get(f"{API}/fhir/Observation/{theirs}", headers=auth).status_code == 404

    def test_posting_a_patient_points_to_patients(self, client, auth):
        resp = client.post(f"{API}/fhir/Patient", headers={**auth, "Content-Type": "application/fhir+json"},
                           content=json.dumps({"resourceType": "Patient"}))
        assert resp.status_code == 400 and "POST /patients" in resp.json()["issue"][0]["diagnostics"]


# --- queue ---------------------------------------------------------------------------------------------------------

class TestQueue:
    def test_check_in_call_done(self, client, auth, hospital, doctor):
        make_patient(hospital, mrn="SPH-000001", dedan_id="DE482731")
        resp = client.post(f"{API}/queue/check-in", headers=auth, json={"doctor_id": doctor,
                                                                         "patient_mrn": "SPH-000001"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["ticket"] == 1 and body["entries"][0]["mrn"] == "SPH-000001"
        assert body["entries"][0]["endod_id"] == "DE482731" and "patient_id" not in body["entries"][0]
        assert [p["status"] for _t, p in outbox("queue.updated")] == ["waiting"]
        assert audits("queue_checked_in")[0]["via"] == "integration"
        walk_in = client.post(f"{API}/queue/check-in", headers=auth, json={
            "doctor_id": doctor, "walk_in": {"name": "Kebede Alemu", "phone": "+251922345678"}})
        assert walk_in.json()["ticket"] == 2
        assert client.post(f"{API}/queue/check-in", headers=auth, json={
            "doctor_id": doctor, "patient_mrn": "SPH-000001"}).status_code == 409
        called = client.post(f"{API}/queue/{doctor}/call-next", headers=auth).json()
        assert called["called"]["ticket"] == 1
        assert client.post(f"{API}/queue/{doctor}/call-next", headers=auth).status_code == 409
        done = client.post(f"{API}/queue/entries/{body['entry_id']}/done", headers=auth)
        assert done.status_code == 200 and done.json()["entries"][0]["status"] == "done"
        skip = client.post(f"{API}/queue/entries/{walk_in.json()['entry_id']}/skip", headers=auth)
        assert skip.json()["waiting"] == 0
        board = client.get(f"{API}/queue", headers=auth).json()
        assert board["queues"][0]["doctor"]["id"] == doctor

    def test_by_booking_links_the_patient(self, client, auth, hospital, doctor, monkeypatch):
        sent = sent_events(monkeypatch)
        make_patient(hospital, mrn="SPH-000001")
        booking = book(hospital)
        resp = client.post(f"{API}/queue/check-in", headers=auth, json={
            "booking_id": booking, "patient_mrn": "SPH-000001", "doctor_id": doctor})
        assert resp.status_code == 201 and resp.json()["entries"][0]["endod_id"] == "DE123456"
        again = client.post(f"{API}/queue/check-in", headers=auth, json={"booking_id": booking, "doctor_id": doctor})
        assert again.status_code == 409
        webhooks.deliver_due()
        assert "patient.linked" in [e["type"] for e in sent]

    def test_scopes_other_hospitals_and_test_mode(self, client, admin, auth, hospital, doctor, test_auth):
        assert client.post(f"{API}/queue/check-in", headers=auth, json={}).status_code == 422
        reader = get_token(client, connected(client, admin, scopes=["bookings.read"], name="Reader"))
        assert client.get(f"{API}/queue", headers=reader).status_code == 403
        assert client.get(f"{API}/doctors", headers=reader).status_code == 403
        assert [d["id"] for d in client.get(f"{API}/doctors", headers=auth).json()["items"]] == [doctor]
        other = make_hospital(code="BET", name="Bethel Hospital")
        their_doctor = make_staff(other, "doc@bet.example", role="doctor")
        make_patient(other, mrn="BET-000001")
        assert client.post(f"{API}/queue/check-in", headers=auth, json={
            "doctor_id": their_doctor, "walk_in": {"name": "X Y", "phone": "+251922345678"}}).status_code == 400
        assert client.post(f"{API}/queue/check-in", headers=auth, json={
            "doctor_id": doctor, "patient_mrn": "BET-000001"}).status_code == 404
        make_patient(hospital, mrn="SPH-000001")
        before = writes()
        resp = client.post(f"{API}/queue/check-in", headers=test_auth, json={"doctor_id": doctor,
                                                                              "patient_mrn": "SPH-404404"})
        assert resp.status_code == 201 and resp.json()["sample"]
        assert client.post(f"{API}/queue/{doctor}/call-next", headers=test_auth).json()["sample"]
        assert client.post(f"{API}/queue/entries/sample-entry-1/done", headers=test_auth).status_code == 200
        assert client.post(f"{API}/queue/entries/nope/done", headers=test_auth).status_code == 404
        assert client.get(f"{API}/queue", headers=test_auth).json()["queues"][0]["sample"]
        assert writes() == before


def test_idempotency_rows_are_per_connection(client, auth, admin):
    other = get_token(client, connected(client, admin, scopes=["patients.write"], name="Second EMR"))
    key = "shared-key-1"
    a = client.post(f"{API}/patients", headers={**auth, "Idempotency-Key": key},
                    json={"full_name": "Almaz Tefera", "sex": "female"})
    b = client.post(f"{API}/patients", headers={**other, "Idempotency-Key": key},
                    json={"full_name": "Almaz Tefera", "sex": "female", "confirm_duplicate": True})
    assert a.status_code == b.status_code == 201 and a.json()["mrn"] != b.json()["mrn"]
    assert count(IntegrationIdempotency) == 2
