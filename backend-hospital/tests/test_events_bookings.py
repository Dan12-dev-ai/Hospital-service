"""Hospital sign-up and approval, the hospital's listing, events with the
patient platform (through a real Redis protocol, in memory) and Endod bookings."""

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest

from conftest import PASSWORD, make_hospital, make_staff, sign_in

PLATFORM_KEY = "platform-test-key"
JITSI_SECRET = "jitsi-test-secret"


@pytest.fixture(autouse=True)
def settings_env(monkeypatch):
    monkeypatch.setenv("HOSPITAL_PLATFORM_ADMIN_KEY", PLATFORM_KEY)
    monkeypatch.setenv("HOSPITAL_JITSI_APP_SECRET", JITSI_SECRET)
    from app.api import onboarding

    onboarding._signups.clear()


@pytest.fixture
def bus():
    return fakeredis.FakeRedis(decode_responses=True)


def stream(bus, name="endod:hospital"):
    return [(fields["type"], json.loads(fields["payload"])) for _id, fields in bus.xrange(name)]


def send(bus, event_type, payload, event_id=None):
    """The patient platform publishing an event."""
    bus.xadd("endod:patient", {"id": event_id or uuid.uuid4().hex, "type": event_type, "source": "platform",
                               "occurred_at": datetime.now(timezone.utc).isoformat(),
                               "payload": json.dumps(payload)})


def run_worker(bus, rounds=1):
    from app import worker

    for _ in range(rounds):
        worker.run_once(bus)


def listed_hospital(client, admin, video=True):
    body = {"latitude": 9.03, "longitude": 38.74, "price_in_person": "150.00", "city": "Addis Ababa",
            "services": ["general_medicine", "emergency"], "ambulance_phone": "907", "emergency": True}
    if video:
        body.update({"price_video": "120.50", "video_enabled": True})
    resp = client.patch("/hospital", headers=admin, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


SIGNUP = {"hospital_name": "Tikur Anbessa Specialized Hospital", "kind": "public", "city": "Addis Ababa",
          "phone": "011 551 7611", "admin_name": "Hiwot Admin", "admin_email": "admin@tash.example",
          "password": "Strong-pass-123"}


class TestOnboarding:
    def test_sign_up_creates_a_pending_hospital_and_signs_in(self, client):
        resp = client.post("/onboarding", json=SIGNUP)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["access_token"] and body["staff"]["role"] == "admin"
        assert body["hospital"]["status"] == "pending" and body["hospital"]["code"] == "TASH"
        assert body["hospital"]["listed"] is False
        headers = {"Authorization": f"Bearer {body['access_token']}"}
        # The portal works while pending.
        assert client.get("/hospital", headers=headers).json()["status"] == "pending"

    @pytest.mark.parametrize("change,status", [
        ({"password": "short"}, 400), ({"kind": "military"}, 400), ({"admin_email": "nope"}, 422),
        ({"hospital_name": " "}, 422),
    ])
    def test_invalid_sign_ups(self, client, change, status):
        assert client.post("/onboarding", json={**SIGNUP, **change}).status_code == status

    def test_codes_stay_unique_and_emails_too(self, client):
        assert client.post("/onboarding", json=SIGNUP).status_code == 201
        second = client.post("/onboarding", json={**SIGNUP, "admin_email": "other@tash.example"})
        assert second.json()["hospital"]["code"] == "TASH2"
        assert client.post("/onboarding", json=SIGNUP).status_code == 409

    def test_sign_ups_are_rate_limited(self, client):
        for i in range(5):
            client.post("/onboarding", json={**SIGNUP, "admin_email": f"a{i}@x.example"})
        assert client.post("/onboarding", json={**SIGNUP, "admin_email": "late@x.example"}).status_code == 429

    def test_sign_up_can_be_closed(self, client, monkeypatch):
        monkeypatch.setenv("HOSPITAL_SIGNUP_ENABLED", "false")
        assert client.post("/onboarding", json=SIGNUP).status_code == 403


class TestApprovalAndListing:
    def test_platform_endpoints_need_the_key(self, client, monkeypatch):
        assert client.get("/platform/hospitals").status_code == 401
        assert client.get("/platform/hospitals", headers={"X-Platform-Key": "wrong"}).status_code == 401
        monkeypatch.delenv("HOSPITAL_PLATFORM_ADMIN_KEY")
        assert client.get("/platform/hospitals", headers={"X-Platform-Key": PLATFORM_KEY}).status_code == 404

    def test_approval_lists_the_hospital_once_complete(self, client, bus):
        signed = client.post("/onboarding", json=SIGNUP).json()
        admin = {"Authorization": f"Bearer {signed['access_token']}"}
        hid = signed["hospital"]["id"]
        key = {"X-Platform-Key": PLATFORM_KEY}
        pending = client.get("/platform/hospitals?status=pending", headers=key).json()
        assert [h["id"] for h in pending] == [hid]

        # Approved but no price/location yet: not listed, and says what is missing.
        approved = client.post(f"/platform/hospitals/{hid}/approve", headers=key).json()
        assert approved["status"] == "approved" and approved["listed"] is False
        assert set(approved["missing_for_listing"]) == {"price_in_person", "location"}

        hospital = listed_hospital(client, admin)
        assert hospital["listed"] is True and hospital["price_video"] == "120.50"
        run_worker(bus)
        events = stream(bus)
        assert [t for t, _ in events] == ["hospital.unlisted", "hospital.listed"]
        snapshot = events[-1][1]
        assert snapshot["price_in_person"] == 15000 and snapshot["price_video"] == 12050
        assert snapshot["services"] == ["general_medicine", "emergency"] and snapshot["ambulance_phone"] == "907"
        assert "admin_email" not in json.dumps(snapshot)

        client.post(f"/platform/hospitals/{hid}/suspend", headers=key)
        run_worker(bus)
        assert stream(bus)[-1] == ("hospital.unlisted", {"hospital_id": hid})

    def test_pending_hospitals_are_never_announced(self, client, bus):
        signed = client.post("/onboarding", json=SIGNUP).json()
        listed_hospital(client, {"Authorization": f"Bearer {signed['access_token']}"})
        run_worker(bus)
        assert stream(bus) == []

    @pytest.mark.parametrize("body", [
        {"video_enabled": True},  # no video price
        {"latitude": 9.0},  # without longitude
        {"services": ["astrology"]},
        {"kind": "military"},
        {"price_in_person": "-1"},
        {"price_in_person": "10.555"},
        {"ambulance_phone": "call us"},
    ])
    def test_invalid_hospital_settings(self, client, admin, body):
        assert client.patch("/hospital", headers=admin, json=body).status_code in (400, 422)

    def test_cli_approves(self, client, capsys):
        client.post("/onboarding", json=SIGNUP)
        from app import cli

        assert cli.main(["approve", "--code", "tash"]) == 0
        assert "TASH: approved" in capsys.readouterr().out


@pytest.fixture
def hospital_ready(client, admin, hospital):
    """The conftest hospital (approved), listed with prices and video."""
    listed_hospital(client, admin)
    return hospital


def request_payload(hospital_id, mode="in_person", when=None, appointment_id=None):
    when = when or datetime.now(timezone.utc) + timedelta(days=1)
    return {"appointment_id": appointment_id or uuid.uuid4().hex, "hospital_id": hospital_id,
            "patient": {"dedan_id": "DE123456", "name": "Almaz Tefera", "phone": "+251911234567"},
            "visit_mode": mode, "service": "general_medicine", "scheduled_at": when.isoformat(),
            "duration_minutes": 30, "notes": "Headache for 3 days", "price": 15000}


class TestBookingsFromThePlatform:
    def test_in_person_is_confirmed_at_once(self, client, admin, bus, hospital_ready):
        payload = request_payload(hospital_ready)
        send(bus, "appointment.requested", payload)
        run_worker(bus)
        items = client.get("/bookings", headers=admin).json()["items"]
        assert len(items) == 1 and items[0]["status"] == "confirmed" and items[0]["price"] == "150.00"
        assert items[0]["patient"]["name"] == "Almaz Tefera"
        run_worker(bus)
        decisions = [e for e in stream(bus) if e[0].startswith("appointment.")]
        assert decisions == [("appointment.confirmed", {
            "appointment_id": payload["appointment_id"], "hospital_id": hospital_ready, "status": "confirmed",
            "meeting_room": None, "doctor_name": None, "reason": None})]

    def test_redelivered_events_are_handled_once(self, client, admin, bus, hospital_ready):
        payload = request_payload(hospital_ready)
        send(bus, "appointment.requested", payload, event_id="evt-1")
        send(bus, "appointment.requested", payload, event_id="evt-1")
        send(bus, "appointment.requested", payload, event_id="evt-2")  # same booking, new event id
        run_worker(bus, rounds=2)
        assert len(client.get("/bookings", headers=admin).json()["items"]) == 1
        assert bus.xpending("endod:patient", "hospital-service")["pending"] == 0

    def test_unknown_or_suspended_hospital_rejects(self, client, admin, bus, hospital_ready):
        send(bus, "appointment.requested", request_payload("nope"))
        run_worker(bus, rounds=2)
        assert stream(bus)[-1][0] == "appointment.rejected"

    def test_video_waits_for_a_doctor_who_approves(self, client, admin, bus, hospital_ready):
        doctor_id = make_staff(hospital_ready, "doc@sph.example", role="doctor")
        doctor = sign_in(client, "doc@sph.example")
        send(bus, "appointment.requested", request_payload(hospital_ready, "video"))
        run_worker(bus)
        booking = client.get("/bookings?status=awaiting_doctor", headers=doctor).json()["items"][0]
        assert booking["visit_mode"] == "video" and booking["has_video_room"] is False

        approved = client.post(f"/bookings/{booking['id']}/approve", headers=doctor, json={})
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "confirmed" and approved.json()["doctor"]["id"] == doctor_id
        run_worker(bus)
        event = stream(bus)[-1]
        assert event[0] == "appointment.confirmed" and event[1]["meeting_room"].startswith("endod-")
        assert event[1]["doctor_name"]
        # A second approval is refused.
        assert client.post(f"/bookings/{booking['id']}/approve", headers=doctor, json={}).status_code == 409

    def test_admin_approves_for_a_named_doctor_only(self, client, admin, bus, hospital_ready):
        doctor_id = make_staff(hospital_ready, "doc@sph.example", role="doctor")
        nurse_id = make_staff(hospital_ready, "nurse@sph.example", role="nurse")
        send(bus, "appointment.requested", request_payload(hospital_ready, "video"))
        run_worker(bus)
        bid = client.get("/bookings", headers=admin).json()["items"][0]["id"]
        assert client.post(f"/bookings/{bid}/approve", headers=admin, json={}).status_code == 400
        assert client.post(f"/bookings/{bid}/approve", headers=admin, json={"doctor_id": nurse_id}).status_code == 400
        assert client.post(f"/bookings/{bid}/approve", headers=admin, json={"doctor_id": doctor_id}).status_code == 200

    def test_reject_cancel_and_complete(self, client, admin, bus, hospital_ready):
        make_staff(hospital_ready, "doc@sph.example", role="doctor")
        doctor = sign_in(client, "doc@sph.example")
        send(bus, "appointment.requested", request_payload(hospital_ready, "video"))
        send(bus, "appointment.requested", request_payload(hospital_ready, "in_person"))
        past = request_payload(hospital_ready, "in_person", when=datetime.now(timezone.utc) + timedelta(seconds=2))
        send(bus, "appointment.requested", past)
        run_worker(bus)
        items = {b["external_id"]: b for b in client.get("/bookings", headers=admin).json()["items"]}
        video = next(b for b in items.values() if b["visit_mode"] == "video")
        in_person = next(b for b in items.values() if b["visit_mode"] == "in_person"
                         and b["external_id"] != past["appointment_id"])

        assert client.post(f"/bookings/{video['id']}/reject", headers=doctor, json={"reason": " "}).status_code == 422
        rejected = client.post(f"/bookings/{video['id']}/reject", headers=doctor, json={"reason": "Fully booked"})
        assert rejected.json()["status"] == "rejected"
        assert client.post(f"/bookings/{in_person['id']}/reject", headers=admin,
                           json={"reason": "x y"}).status_code == 409  # confirmed: cancel instead
        assert client.post(f"/bookings/{in_person['id']}/complete", headers=doctor).status_code == 409  # future
        cancelled = client.post(f"/bookings/{in_person['id']}/cancel", headers=admin, json={"reason": "Doctor ill"})
        assert cancelled.json()["status"] == "cancelled"

        # A visit that has started can be completed.
        import time
        time.sleep(2.2)
        started = items[past["appointment_id"]]
        assert client.post(f"/bookings/{started['id']}/complete", headers=doctor).json()["status"] == "completed"

        run_worker(bus)
        types = [t for t, _ in stream(bus) if t.startswith("appointment.")]
        assert types.count("appointment.rejected") == 1 and types.count("appointment.cancelled") == 1
        assert types.count("appointment.completed") == 1
        assert [p for t, p in stream(bus) if t == "appointment.cancelled"][0]["by"] == "hospital"

    def test_patient_cancellation_closes_the_booking(self, client, admin, bus, hospital_ready):
        payload = request_payload(hospital_ready)
        send(bus, "appointment.requested", payload)
        send(bus, "appointment.cancelled", {"appointment_id": payload["appointment_id"], "by": "patient"})
        run_worker(bus)
        booking = client.get("/bookings", headers=admin).json()["items"][0]
        assert booking["status"] == "cancelled" and booking["reason"] == "Cancelled by the patient."

    def test_bookings_belong_to_their_hospital(self, client, admin, bus, hospital_ready):
        send(bus, "appointment.requested", request_payload(hospital_ready))
        run_worker(bus)
        other = make_hospital(code="BLH", name="Black Lion")
        make_staff(other, "admin@blh.example")
        stranger = sign_in(client, "admin@blh.example")
        assert client.get("/bookings", headers=stranger).json()["items"] == []
        bid = client.get("/bookings", headers=admin).json()["items"][0]["id"]
        assert client.get(f"/bookings/{bid}", headers=stranger).status_code == 404
        assert client.post(f"/bookings/{bid}/cancel", headers=stranger, json={"reason": "no no"}).status_code == 404

    def test_pharmacists_do_not_see_bookings(self, client, hospital_ready):
        make_staff(hospital_ready, "rx@sph.example", role="pharmacist")
        assert client.get("/bookings", headers=sign_in(client, "rx@sph.example")).status_code == 403


class TestVideoJoin:
    def _approved(self, client, admin, bus, hospital, when):
        make_staff(hospital, "doc@sph.example", role="doctor")
        doctor = sign_in(client, "doc@sph.example")
        send(bus, "appointment.requested", request_payload(hospital, "video", when=when))
        run_worker(bus)
        bid = client.get("/bookings", headers=doctor).json()["items"][0]["id"]
        client.post(f"/bookings/{bid}/approve", headers=doctor, json={})
        return doctor, bid

    def test_the_doctor_gets_a_signed_token_around_the_visit(self, client, admin, bus, hospital_ready):
        doctor, bid = self._approved(client, admin, bus, hospital_ready,
                                     datetime.now(timezone.utc) + timedelta(minutes=10))
        resp = client.post(f"/bookings/{bid}/video", headers=doctor)
        assert resp.status_code == 200, resp.text
        details = resp.json()
        assert details["domain"] == "meet.endod-health.com" and details["url"].endswith(details["room"])
        head, body, sig = details["jwt"].split(".")
        expected = hmac.new(JITSI_SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
        assert base64.urlsafe_b64decode(sig + "==") == expected
        claims = json.loads(base64.urlsafe_b64decode(body + "=="))
        assert claims["room"] == details["room"] and claims["context"]["user"]["moderator"] is True
        assert claims["aud"] == "jitsi" and claims["exp"] > claims["nbf"]

    def test_too_early_and_other_staff_are_refused(self, client, admin, bus, hospital_ready):
        doctor, bid = self._approved(client, admin, bus, hospital_ready,
                                     datetime.now(timezone.utc) + timedelta(days=2))
        assert client.post(f"/bookings/{bid}/video", headers=doctor).status_code == 409
        make_staff(hospital_ready, "doc2@sph.example", role="doctor")
        assert client.post(f"/bookings/{bid}/video", headers=sign_in(client, "doc2@sph.example")).status_code == 404
        assert client.post(f"/bookings/{bid}/video", headers=admin).status_code == 403

    def test_no_secret_means_no_video(self, client, admin, bus, hospital_ready, monkeypatch):
        doctor, bid = self._approved(client, admin, bus, hospital_ready,
                                     datetime.now(timezone.utc) + timedelta(minutes=5))
        monkeypatch.delenv("HOSPITAL_JITSI_APP_SECRET")
        assert client.post(f"/bookings/{bid}/video", headers=doctor).status_code == 503


class TestEventDelivery:
    def test_events_wait_in_the_database_while_redis_is_down(self, client, admin, hospital_ready):
        from sqlalchemy import func, select

        from app.db import session_scope
        from app.models import OutboxEvent

        with session_scope() as session:
            waiting = session.scalar(select(func.count()).select_from(OutboxEvent)
                                     .where(OutboxEvent.published_at.is_(None)))
        assert waiting >= 1  # the listing, not sent yet
        bus = fakeredis.FakeRedis(decode_responses=True)
        run_worker(bus)
        assert stream(bus)[0][0] == "hospital.listed"

    def test_a_failing_event_is_retried_then_dead_lettered(self, client, bus, hospital_ready, monkeypatch):
        from app import bookings, eventbus

        calls = []

        def broken(session, payload):
            calls.append(1)
            raise RuntimeError("boom")

        monkeypatch.setitem(bookings.HANDLERS, "appointment.requested", broken)
        monkeypatch.setattr(eventbus, "RETRY_AFTER_MS", 0)
        send(bus, "appointment.requested", request_payload(hospital_ready))
        for _ in range(eventbus.MAX_DELIVERIES + 1):
            eventbus.consume_once(bus, bookings.HANDLERS, block_ms=10)
        assert len(calls) == eventbus.MAX_DELIVERIES
        assert len(bus.xrange("endod:dead-letter")) == 1
        assert bus.xpending("endod:patient", "hospital-service")["pending"] == 0

    def test_sentinel_settings_are_used_when_present(self, monkeypatch):
        from redis.sentinel import SentinelManagedConnection

        from app import eventbus

        monkeypatch.setenv("HOSPITAL_REDIS_SENTINELS", "s1:26379,s2:26380")
        monkeypatch.setenv("HOSPITAL_REDIS_SENTINEL_MASTER", "endod")
        client = eventbus.connect()
        assert client.connection_pool.connection_class is SentinelManagedConnection
        hosts = [(c.connection_pool.connection_kwargs["host"], c.connection_pool.connection_kwargs["port"])
                 for c in client.connection_pool.sentinel_manager.sentinels]
        assert hosts == [("s1", 26379), ("s2", 26380)]
