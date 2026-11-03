"""Enrolling patients without an Endod account by SMS (docs/history-events.md
section 8, docs/integrations.md section 4): the integration API, the events
to and from Endod, the webhooks, test mode."""

import pytest
from sqlalchemy import select

from test_integrations_journey import (  # noqa: F401  (fixtures and helpers)
    API, JOURNEY, admin, audits, auth, client, connected, fresh_limits, live, outbox, register, sent_events,
    test_auth, writes,
)

from app import linking
from app.db import platform_session
from app.integrations import webhooks
from app.models import Patient, SmsEnrolment

MRN = "SPH-000001"


def enrol(client, auth, **body):
    return client.post(f"{API}/patients/{MRN}/sms-enrol", headers=auth, json=body)


def verify(client, auth, code="482913", **body):
    return client.post(f"{API}/patients/{MRN}/sms-enrol/verify", headers=auth, json={"code": code, **body})


def requested():
    return outbox("patient.sms_enrol_requested")[-1][1]


def echo(request):
    return {k: request[k] for k in ("request_id", "hospital_id", "patient_id")}


def reply(handler, payload):
    with platform_session() as session:
        handler(session, payload)


def state(client, auth):
    return client.get(f"{API}/patients/{MRN}", headers=auth).json()["link"]


class TestEnrolment:
    def test_code_then_verify_then_enrolled_and_linked(self, client, auth, monkeypatch):
        sent = sent_events(monkeypatch)
        register(client, auth)
        resp = enrol(client, auth)
        assert resp.status_code == 202, resp.text
        assert resp.json()["status"] == "sending"
        request = requested()
        # The phone only: nothing else about the patient before the code.
        assert set(request) == {"request_id", "hospital_id", "patient_id", "phone"}
        assert request["phone"] == "+251911234567" and request["request_id"] == resp.json()["id"]
        assert audits("patient_sms_enrol_requested")[0]["via"] == "integration"

        reply(linking.on_sms_code_sent, {**echo(request), "expires_at": "2026-11-03T10:10:00+00:00"})
        assert state(client, auth)["sms_enrolment"]["status"] == "code_sent"

        resp = verify(client, auth, code=" 482913 ", language="en")
        assert resp.status_code == 202, resp.text
        assert resp.json()["status"] == "verifying"
        [(_, check)] = outbox("patient.sms_enrol_verify")
        assert check == {**echo(request), "code": "482913", "name": "Almaz Tefera", "language": "en"}
        assert "482913" not in str(audits("patient_sms_enrol_verified"))

        reply(linking.on_sms_enrolled, {**echo(request), "dedan_id": "DE482731", "name": "Almaz Tefera",
                                        "phone": "+251911234567", "created": True})
        link = state(client, auth)
        assert link["status"] == "linked" and link["endod_id"] == "DE482731"
        assert link["sms_enrolment"]["status"] == "enrolled" and link["sms_enrolment"]["created_account"] is True
        # The history goes to Endod as on any link.
        with platform_session() as session:
            assert session.scalar(select(Patient)).dedan_id == "DE482731"
        webhooks.deliver_due()
        types = [(e["type"], e["data"].get("status")) for e in sent]
        assert types == [("patient.sms_enrolment", "code_sent"), ("patient.linked", None),
                         ("patient.sms_enrolment", "enrolled")]

    def test_a_wrong_code_may_be_typed_again_then_it_fails_for_good(self, client, auth):
        register(client, auth)
        enrol(client, auth)
        request = requested()
        reply(linking.on_sms_code_sent, echo(request))
        verify(client, auth)
        reply(linking.on_sms_refused, {**echo(request), "reason": "wrong_code", "attempts_left": 2})
        enrolment = state(client, auth)["sms_enrolment"]
        assert (enrolment["status"], enrolment["reason"], enrolment["attempts_left"]) == ("code_sent", "wrong_code", 2)
        assert verify(client, auth).status_code == 202
        reply(linking.on_sms_refused, {**echo(request), "reason": "expired", "attempts_left": None})
        assert state(client, auth)["sms_enrolment"]["status"] == "failed"
        assert verify(client, auth).status_code == 409  # a new code first

    def test_refusals_and_invalid_requests(self, client, auth):
        assert enrol(client, auth).status_code == 404
        register(client, auth, phone=None)
        assert enrol(client, auth).status_code == 400  # no phone to text
        assert enrol(client, auth, phone="12345").status_code in (400, 422)
        assert verify(client, auth).status_code == 409  # nothing asked
        assert enrol(client, auth, phone="0922334455").status_code == 202
        assert requested()["phone"] == "+251922334455"
        assert verify(client, auth, code="12ab56").status_code in (400, 422)
        reply(linking.on_sms_refused, {**echo(requested()), "reason": "rate_limited"})
        assert state(client, auth)["sms_enrolment"]["reason"] == "rate_limited"
        with platform_session() as session:
            session.scalar(select(Patient)).dedan_id = "DE482731"
        assert enrol(client, auth).status_code == 409  # already linked

    def test_a_newer_request_replaces_the_last_and_late_replies_are_ignored(self, client, auth):
        register(client, auth)
        enrol(client, auth)
        first = requested()
        enrol(client, auth)
        second = requested()
        assert first["request_id"] != second["request_id"]
        reply(linking.on_sms_enrolled, {**echo(first), "dedan_id": "DE482731", "created": True})
        assert state(client, auth)["status"] == "not_linked"
        with platform_session() as session:
            statuses = {r.id: r.status for r in session.scalars(select(SmsEnrolment))}
        assert statuses == {first["request_id"]: "superseded", second["request_id"]: "sending"}

    def test_an_endod_id_held_by_another_patient_fails(self, client, auth, hospital):
        register(client, auth)
        register(client, auth, full_name="Almaz T.", phone="+251933000000", confirm_duplicate=True)
        with platform_session() as session:
            other = session.scalar(select(Patient).where(Patient.mrn == "SPH-000002"))
            other.dedan_id = "DE482731"
        enrol(client, auth)
        request = requested()
        reply(linking.on_sms_enrolled, {**echo(request), "dedan_id": "DE482731", "created": False})
        enrolment = state(client, auth)["sms_enrolment"]
        assert (enrolment["status"], enrolment["reason"]) == ("failed", "already_linked")

    def test_replies_for_another_patient_are_dead_lettered(self, client, auth):
        from app.eventbus import PermanentEventError

        register(client, auth)
        enrol(client, auth)
        with pytest.raises(PermanentEventError):
            reply(linking.on_sms_code_sent, {**echo(requested()), "patient_id": "x" * 32})

    def test_test_mode_writes_nothing_and_texts_nobody(self, client, test_auth):
        before = writes()
        resp = enrol(client, test_auth)
        assert resp.status_code == 202 and resp.json()["sample"] is True and resp.json()["status"] == "sending"
        resp = verify(client, test_auth)
        assert resp.json()["status"] == "verifying" and resp.json()["sample"] is True
        wrong = verify(client, test_auth, code="000000").json()
        assert (wrong["status"], wrong["reason"], wrong["attempts_left"]) == ("code_sent", "wrong_code", 4)
        assert verify(client, test_auth, code="12").status_code in (400, 422)
        assert writes() == before and outbox("patient.sms_enrol_requested") == []

    def test_needs_patients_write(self, client, admin):
        from test_integrations import get_token

        reader = get_token(client, connected(client, admin, scopes=["patients.read"], name="Reader"))
        assert enrol(client, reader).status_code == 403
        assert verify(client, reader).status_code == 403
