"""Linking hospital patients to Endod accounts (docs/history-events.md, section 1)."""

import uuid

import pytest

from history_support import (  # noqa: F401  (fixtures)
    bus, consume, dead_letters, events, link_directly, platform_key, register, send, staff,
)

CARD = "https://endod-health.com/card/DE482731?s=c2lnbmF0dXJlLWZvci10ZXN0cw"


@pytest.fixture
def desk(client, hospital):
    return staff(client, hospital, "reception")


@pytest.fixture
def patient(client, desk):
    return register(client, desk)


def ask(client, headers, patient_id, **body):
    return client.post(f"/patients/{patient_id}/link", headers=headers, json=body)


def reply(bus, request, kind="patient.linked", event_id=None, **changes):
    payload = {"request_id": request["request_id"], "hospital_id": request["hospital_id"],
               "patient_id": request["patient_id"], "dedan_id": request["dedan_id"]}
    if kind == "patient.linked":
        payload.update(name="Almaz Tefera", phone="+251911234567")
    else:
        payload.update(reason="not_verified")
    payload.update(changes)
    send(bus, kind, payload, event_id)
    consume(bus)


class TestRequests:
    def test_by_endod_id_and_phone(self, client, desk, patient, bus, hospital):
        resp = ask(client, desk, patient["id"], dedan_id="de-482731", phone="0911 234 567")
        assert resp.status_code == 202, resp.text
        assert resp.json()["dedan_id"] is None  # not before Endod confirms
        assert resp.json()["request"]["status"] == "pending"
        [sent] = events(bus, "patient.link_requested")
        assert sent == {"request_id": resp.json()["request"]["id"], "hospital_id": hospital,
                        "patient_id": patient["id"], "dedan_id": "DE482731", "card_signature": None,
                        "phone": "+251911234567"}
        # Nothing else about the patient goes to Endod before the link.
        assert [t for t, _ in events(bus)] == ["patient.link_requested"]

    def test_by_health_card(self, client, desk, patient, bus):
        resp = ask(client, desk, patient["id"], card_url=CARD)
        assert resp.status_code == 202, resp.text
        assert resp.json()["request"]["method"] == "card"
        [sent] = events(bus, "patient.link_requested")
        assert sent["dedan_id"] == "DE482731" and sent["card_signature"] == "c2lnbmF0dXJlLWZvci10ZXN0cw"
        assert sent["phone"] is None

    @pytest.mark.parametrize("body", [
        {"card_url": "https://evil.example/card/DE482731?s=c2lnbmF0dXJlLWZvci10ZXN0cw"},
        {"card_url": "http://endod-health.com/card/DE482731?s=c2lnbmF0dXJlLWZvci10ZXN0cw"},
        {"card_url": "https://endod-health.com/card/DE482731"},
        {"card_url": "https://endod-health.com/card/../admin?s=c2lnbmF0dXJlLWZvci10ZXN0cw"},
        {"dedan_id": "DE482731"},  # no phone
        {"dedan_id": "XY12", "phone": "0911234567"},
        {"phone": "0911234567"},
    ])
    def test_invalid_requests(self, client, desk, patient, body):
        assert ask(client, desk, patient["id"], **body).status_code in (400, 422)

    def test_who_may_link(self, client, hospital, patient):
        for role, allowed in (("nurse", False), ("billing", False), ("doctor", False), ("records", True),
                              ("admin", True)):
            resp = ask(client, staff(client, hospital, role), patient["id"], dedan_id="DE482731",
                       phone="0911234567")
            assert (resp.status_code == 202) is allowed, (role, resp.text)

    def test_other_hospitals_patients_are_not_found(self, client, patient):
        from conftest import make_hospital

        other = make_hospital(code="BLH", name="Black Lion")
        desk = staff(client, other, "reception", "desk-blh")
        assert ask(client, desk, patient["id"], dedan_id="DE482731", phone="0911234567").status_code == 404
        assert client.get(f"/patients/{patient['id']}/link", headers=desk).status_code == 404


class TestReplies:
    def _request(self, client, desk, patient, bus):
        ask(client, desk, patient["id"], dedan_id="DE482731", phone="0911234567")
        return events(bus, "patient.link_requested")[-1]

    def test_linked(self, client, desk, patient, bus):
        request = self._request(client, desk, patient, bus)
        reply(bus, request)
        state = client.get(f"/patients/{patient['id']}/link", headers=desk).json()
        assert state["dedan_id"] == "DE482731"
        assert state["request"]["status"] == "linked" and state["request"]["linked_name"] == "Almaz Tefera"
        assert client.get(f"/patients/{patient['id']}", headers=desk).json()["dedan_id"] == "DE482731"

    def test_linked_twice_is_handled_once(self, client, desk, patient, bus):
        request = self._request(client, desk, patient, bus)
        reply(bus, request, event_id="evt-1")
        reply(bus, request, event_id="evt-1")
        reply(bus, request, event_id="evt-2")  # a resend under a new id
        assert client.get(f"/patients/{patient['id']}/link", headers=desk).json()["dedan_id"] == "DE482731"
        assert bus.xpending("endod:patient", "hospital-service")["pending"] == 0
        assert dead_letters(bus) == []

    def test_refused(self, client, desk, patient, bus):
        request = self._request(client, desk, patient, bus)
        reply(bus, request, "patient.link_refused", reason="not_found")
        reply(bus, request, "patient.link_refused", reason="not_found")
        state = client.get(f"/patients/{patient['id']}/link", headers=desk).json()
        assert state["dedan_id"] is None
        assert state["request"]["status"] == "refused" and state["request"]["reason"] == "not_found"
        # A late "linked" for a refused request changes nothing.
        reply(bus, request)
        assert client.get(f"/patients/{patient['id']}/link", headers=desk).json()["dedan_id"] is None

    def test_a_replaced_request_is_ignored(self, client, desk, patient, bus):
        first = self._request(client, desk, patient, bus)
        ask(client, desk, patient["id"], dedan_id="DE111111", phone="0911234567")
        reply(bus, first)
        state = client.get(f"/patients/{patient['id']}/link", headers=desk).json()
        assert state["dedan_id"] is None and state["request"]["dedan_id"] == "DE111111"

    def test_one_endod_id_per_patient(self, client, desk, patient, bus):
        other = register(client, desk, name="Someone Else", phone="0922000111")
        link_directly(other["id"], "DE482731")
        resp = ask(client, desk, patient["id"], dedan_id="DE482731", phone="0911234567")
        assert resp.status_code == 409 and "Someone Else" in resp.json()["error"]
        # Already linked patients must be unlinked first.
        assert ask(client, desk, other["id"], dedan_id="DE222222", phone="0911234567").status_code == 409

    def test_a_reply_after_someone_else_took_the_id_is_refused(self, client, desk, patient, bus):
        request = self._request(client, desk, patient, bus)
        other = register(client, desk, name="Someone Else", phone="0922000111")
        link_directly(other["id"], "DE482731")
        reply(bus, request)
        state = client.get(f"/patients/{patient['id']}/link", headers=desk).json()
        assert state["dedan_id"] is None and state["request"]["reason"] == "already_linked"
        assert dead_letters(bus) == []

    @pytest.mark.parametrize("change", [{"patient_id": "x" * 32}, {"dedan_id": "DE999999"}, {"dedan_id": "nope"},
                                        {"request_id": "not-hex"}])
    def test_mismatched_or_malformed_replies_are_dead_lettered(self, client, desk, patient, bus, change):
        request = self._request(client, desk, patient, bus)
        reply(bus, request, **change)
        assert len(dead_letters(bus)) == 1
        assert client.get(f"/patients/{patient['id']}/link", headers=desk).json()["dedan_id"] is None

    def test_a_reply_for_an_unknown_request_is_dropped(self, client, desk, patient, bus):
        reply(bus, {"request_id": uuid.uuid4().hex, "hospital_id": "h", "patient_id": "p", "dedan_id": "DE123456"})
        assert dead_letters(bus) == [] and bus.xpending("endod:patient", "hospital-service")["pending"] == 0

    def test_linking_publishes_the_history(self, client, desk, patient, bus, hospital):
        doctor = staff(client, hospital, "doctor")
        client.post(f"/patients/{patient['id']}/records", headers=doctor, json={
            "category": "diagnosis", "title": "Malaria", "details": {"condition": "Malaria"}})
        assert events(bus, "record.published") == []  # not linked yet
        request = self._request(client, desk, patient, bus)
        reply(bus, request)
        [published] = events(bus, "record.published")
        assert published["dedan_id"] == "DE482731" and published["title"] == "Malaria"


class TestUnlinking:
    def test_unlink_stops_publishing(self, client, desk, patient, bus, hospital):
        link_directly(patient["id"], "DE482731")
        resp = client.delete(f"/patients/{patient['id']}/link", headers=desk)
        assert resp.status_code == 200 and resp.json()["dedan_id"] is None
        doctor = staff(client, hospital, "doctor")
        client.post(f"/patients/{patient['id']}/records", headers=doctor, json={
            "category": "diagnosis", "title": "Malaria", "details": {"condition": "Malaria"}})
        assert events(bus, "record.published") == []

    def test_unlink_withdraws_a_pending_request(self, client, desk, patient, bus):
        ask(client, desk, patient["id"], dedan_id="DE482731", phone="0911234567")
        request = events(bus, "patient.link_requested")[-1]
        assert client.delete(f"/patients/{patient['id']}/link", headers=desk).json()["request"]["status"] == "superseded"
        reply(bus, request)
        assert client.get(f"/patients/{patient['id']}/link", headers=desk).json()["dedan_id"] is None

    def test_nurses_cannot_unlink(self, client, hospital, patient):
        link_directly(patient["id"], "DE482731")
        assert client.delete(f"/patients/{patient['id']}/link",
                             headers=staff(client, hospital, "nurse")).status_code == 403
