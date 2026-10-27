"""Doctors' queues (docs/history-events.md, section 4)."""

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from history_support import (  # noqa: F401  (fixtures)
    bus, consume, events, link_directly, platform_key, register, send, staff, today,
)


@pytest.fixture
def desk(client, hospital):
    return staff(client, hospital, "reception")


@pytest.fixture
def doctor(client, hospital):
    return staff(client, hospital, "doctor")


def doctor_id(headers):
    return headers["X-Staff-Id"]


def walk_in(client, desk, doctor, name, phone="0911000001"):
    resp = client.post("/queue/check-in", headers=desk, json={
        "doctor_id": doctor_id(doctor), "walk_in": {"name": name, "phone": phone}})
    assert resp.status_code == 201, resp.text
    return resp.json()


def set_notify(client, admin, n):
    resp = client.patch("/hospital", headers=admin, json={"queue_notify_ahead": n})
    assert resp.status_code == 200, resp.text


def queue_of(client, headers, who):
    data = client.get("/queue", headers=headers).json()
    return next(q for q in data["queues"] if q["doctor"]["id"] == doctor_id(who))


class TestCheckIn:
    def test_tickets_and_listing(self, client, desk, doctor, hospital):
        other = staff(client, hospital, "doctor", "doc2")
        assert walk_in(client, desk, doctor, "Abebe")["ticket"] == 1
        assert walk_in(client, desk, doctor, "Kebede")["ticket"] == 2
        assert walk_in(client, desk, other, "Chaltu")["ticket"] == 1  # one queue per doctor
        listing = client.get("/queue", headers=desk).json()
        assert listing["day"] == today().isoformat() and listing["notify_ahead"] == 3
        assert {q["doctor"]["id"] for q in listing["queues"]} == {doctor_id(doctor), doctor_id(other)}
        mine = client.get("/queue", headers=doctor).json()["queues"]
        assert [q["doctor"]["id"] for q in mine] == [doctor_id(doctor)]
        assert [(e["ticket"], e["ahead"]) for e in mine[0]["entries"]] == [(1, 0), (2, 1)]

    @pytest.mark.parametrize("body", [
        {"walk_in": {"name": "No Phone"}},
        {"walk_in": {"name": "Bad Phone", "phone": "123"}},
        {},
        {"walk_in": {"name": "Both", "phone": "0911000001"}, "patient_id": "x"},
    ])
    def test_invalid_check_ins(self, client, desk, doctor, body):
        resp = client.post("/queue/check-in", headers=desk, json={"doctor_id": doctor_id(doctor), **body})
        assert resp.status_code in (400, 422)

    def test_a_doctor_is_needed(self, client, desk, hospital):
        nurse = staff(client, hospital, "nurse")
        for doctor in (None, doctor_id(nurse), "f" * 32):
            resp = client.post("/queue/check-in", headers=desk,
                               json={"doctor_id": doctor, "walk_in": {"name": "Abebe", "phone": "0911000001"}})
            assert resp.status_code == 400

    def test_who_checks_in(self, client, hospital, doctor):
        for role, allowed in (("admin", True), ("reception", True), ("doctor", False), ("nurse", False),
                              ("billing", False)):
            headers = staff(client, hospital, role, f"{role}-q")
            resp = client.post("/queue/check-in", headers=headers, json={
                "doctor_id": doctor_id(doctor), "walk_in": {"name": "Abebe", "phone": "0911000001"}})
            assert (resp.status_code == 201) is allowed, role
        assert client.get("/queue", headers=staff(client, hospital, "nurse", "nurse-r")).status_code == 403

    def test_a_registered_patient_once_per_queue(self, client, desk, doctor):
        patient = register(client, desk)
        body = {"doctor_id": doctor_id(doctor), "patient_id": patient["id"]}
        entry = client.post("/queue/check-in", headers=desk, json=body)
        assert entry.status_code == 201
        assert entry.json()["entries"][0]["patient_name"] == "Almaz Tefera"
        assert client.post("/queue/check-in", headers=desk, json=body).status_code == 409


class TestBookingCheckIn:
    def _booking(self, client, admin, bus, hospital, dedan="DE123456"):
        client.patch("/hospital", headers=admin, json={"latitude": 9.03, "longitude": 38.74,
                                                       "price_in_person": "150.00"})
        send(bus, "appointment.requested", {
            "appointment_id": uuid.uuid4().hex, "hospital_id": hospital,
            "patient": {"dedan_id": dedan, "name": "Almaz Tefera", "phone": "+251911234567"},
            "visit_mode": "in_person", "scheduled_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "price": 15000})
        consume(bus)
        return client.get("/bookings", headers=admin).json()["items"][-1]

    def test_checking_in_a_booking_links_the_patient(self, client, admin, desk, doctor, bus, hospital):
        booking = self._booking(client, admin, bus, hospital, dedan="DE-123456")
        patient = register(client, desk)
        nurse = staff(client, hospital, "nurse")
        client.post(f"/patients/{patient['id']}/records", headers=nurse, json={
            "category": "visit_note", "title": "Triage", "details": {"complaint": "Headache"}})
        resp = client.post("/queue/check-in", headers=desk, json={
            "doctor_id": doctor_id(doctor), "booking_id": booking["id"], "patient_id": patient["id"]})
        assert resp.status_code == 201, resp.text
        assert client.get(f"/patients/{patient['id']}", headers=desk).json()["dedan_id"] == "DE123456"
        # No link request: the platform identified the patient when they booked.
        assert events(bus, "patient.link_requested") == []
        assert [e["title"] for e in events(bus, "record.published")] == ["Triage"]
        [update] = events(bus, "queue.updated")
        assert update["dedan_id"] == "DE123456" and update["status"] == "waiting"
        # Once per booking.
        again = client.post("/queue/check-in", headers=desk, json={
            "doctor_id": doctor_id(doctor), "booking_id": booking["id"]})
        assert again.status_code == 409

    def test_the_linked_patient_is_found_by_the_booking(self, client, admin, desk, doctor, bus, hospital):
        booking = self._booking(client, admin, bus, hospital)
        patient = register(client, desk)
        link_directly(patient["id"], "DE123456")
        resp = client.post("/queue/check-in", headers=desk, json={"doctor_id": doctor_id(doctor),
                                                                 "booking_id": booking["id"]})
        assert resp.json()["entries"][0]["patient_id"] == patient["id"]

    def test_a_booking_for_someone_else_is_refused(self, client, admin, desk, doctor, bus, hospital):
        booking = self._booking(client, admin, bus, hospital)
        patient = register(client, desk)
        link_directly(patient["id"], "DE999999")
        resp = client.post("/queue/check-in", headers=desk, json={
            "doctor_id": doctor_id(doctor), "booking_id": booking["id"], "patient_id": patient["id"]})
        assert resp.status_code == 409


class TestCalling:
    def test_call_next_done_skip_cancel(self, client, desk, doctor):
        walk_in(client, desk, doctor, "Abebe")
        walk_in(client, desk, doctor, "Kebede")
        walk_in(client, desk, doctor, "Chaltu")
        resp = client.post(f"/queue/{doctor_id(doctor)}/call-next", headers=doctor)
        assert resp.status_code == 200 and resp.json()["called"]["patient_name"] == "Abebe"
        # A second click calls nobody while Abebe is still called.
        again = client.post(f"/queue/{doctor_id(doctor)}/call-next", headers=doctor)
        assert again.status_code == 409 and "Abebe" in again.json()["error"]
        entries = {e["patient_name"]: e for e in resp.json()["entries"]}
        assert client.post(f"/queue/entries/{entries['Kebede']['id']}/done", headers=doctor).status_code == 409
        assert client.post(f"/queue/entries/{entries['Abebe']['id']}/done", headers=doctor).status_code == 200
        assert client.post(f"/queue/entries/{entries['Kebede']['id']}/skip", headers=desk).status_code == 200
        after = client.post(f"/queue/{doctor_id(doctor)}/call-next", headers=desk).json()
        assert after["called"]["patient_name"] == "Chaltu"
        assert client.post(f"/queue/entries/{entries['Chaltu']['id']}/cancel", headers=desk).status_code == 200
        assert client.post(f"/queue/{doctor_id(doctor)}/call-next", headers=desk).status_code == 409  # empty
        assert client.post(f"/queue/entries/{entries['Abebe']['id']}/teleport", headers=desk).status_code == 404

    def test_a_doctor_runs_only_their_own_queue(self, client, desk, doctor, hospital):
        other = staff(client, hospital, "doctor", "doc2")
        entry = walk_in(client, desk, other, "Abebe")
        assert client.post(f"/queue/{doctor_id(other)}/call-next", headers=doctor).status_code == 403
        assert client.post(f"/queue/entries/{entry['entry_id']}/cancel", headers=doctor).status_code == 403
        assert client.post(f"/queue/{doctor_id(other)}/call-next", headers=other).status_code == 200

    def test_other_hospitals_cannot_touch_the_queue(self, client, desk, doctor):
        from conftest import make_hospital

        entry = walk_in(client, desk, doctor, "Abebe")
        stranger = staff(client, make_hospital(code="BLH", name="Black Lion"), "reception", "desk-blh")
        assert client.post(f"/queue/{doctor_id(doctor)}/call-next", headers=stranger).status_code == 400
        assert client.post(f"/queue/entries/{entry['entry_id']}/cancel", headers=stranger).status_code == 404

    def test_two_clicks_at_once_call_one_patient(self, client, desk, doctor, hospital, monkeypatch):
        """Two "call next" at the same moment: the queue row lock makes the
        second wait for the first, then see someone already called."""
        from app import queues
        from app.db import session_scope

        walk_in(client, desk, doctor, "Abebe")
        walk_in(client, desk, doctor, "Kebede")
        original = queues.entries

        def slow_entries(session, queue_id):
            rows = original(session, queue_id)
            time.sleep(0.3)  # both requests would read "nobody called" here without the lock
            return rows

        monkeypatch.setattr(queues, "entries", slow_entries)
        results = []
        barrier = threading.Barrier(2)

        def click():
            barrier.wait()
            try:
                with session_scope(hospital) as session:  # as a staff request would
                    queue = queues.lock_queue(session, hospital, doctor_id(doctor), today())
                    results.append(queues.call_next(session, queue).patient_name)
            except queues.QueueError as exc:
                results.append(f"refused: {exc}")

        threads = [threading.Thread(target=click) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        monkeypatch.setattr(queues, "entries", original)
        called = [e for e in queue_of(client, desk, doctor)["entries"] if e["status"] == "called"]
        assert [e["patient_name"] for e in called] == ["Abebe"]
        assert sorted(r.split(":")[0] for r in results) == ["Abebe", "refused"]


class TestNotifications:
    def test_near_and_turn_are_sent_once_each(self, client, admin, desk, doctor, bus):
        set_notify(client, admin, 1)
        patient = register(client, desk)
        link_directly(patient["id"], "DE482731")
        client.post("/queue/check-in", headers=desk, json={"doctor_id": doctor_id(doctor), "patient_id": patient["id"]})
        walk_in(client, desk, doctor, "Kebede", "0911000002")
        walk_in(client, desk, doctor, "Chaltu", "0911000003")
        walk_in(client, desk, doctor, "Desta")  # three ahead
        q = queue_of(client, desk, doctor)
        ids = {e["patient_name"]: e["id"] for e in q["entries"]}

        call_next = f"/queue/{doctor_id(doctor)}/call-next"
        client.post(call_next, headers=doctor)  # Almaz
        client.post(f"/queue/entries/{ids['Almaz Tefera']}/done", headers=doctor)
        client.post(call_next, headers=doctor)  # Kebede
        client.post(f"/queue/entries/{ids['Kebede']}/done", headers=doctor)
        client.post(call_next, headers=doctor)  # Chaltu

        sent = events(bus, "queue.updated")
        by_entry = {}
        for e in sent:
            by_entry.setdefault(e["patient_name"], []).append(e)
        notifies = {name: [e["notify"] for e in items if e["notify"]] for name, items in by_entry.items()}
        # No "near" at check-in: Almaz (0 ahead) and Kebede (1 ahead) were already
        # within the threshold, so only "turn"; Chaltu (2) and Desta (3) get "near"
        # once, when the people ahead come down to 1.
        assert notifies == {"Almaz Tefera": ["turn"], "Kebede": ["turn"],
                            "Chaltu": ["near", "turn"], "Desta": ["near"]}
        # Walk-ins (no Endod account) get only the notifications; the linked patient every change.
        assert all(e["notify"] for name, items in by_entry.items() if name != "Almaz Tefera" for e in items)
        almaz = by_entry["Almaz Tefera"]
        assert [e["status"] for e in almaz] == ["waiting", "called", "done"]
        assert [e["seq"] for e in almaz] == [1, 2, 3]
        first = almaz[0]
        assert set(first) == {"entry_id", "hospital_id", "hospital_name", "doctor_name", "day", "ticket", "status",
                              "ahead", "dedan_id", "phone", "patient_name", "notify", "seq"}
        assert first["day"] == today().isoformat() and first["ticket"] == 1 and first["dedan_id"] == "DE482731"
        desta_near = by_entry["Desta"][0]
        assert desta_near["ahead"] == 1 and desta_near["phone"] == "+251911000001"

    def test_a_linked_entry_follows_every_move(self, client, admin, desk, doctor, bus):
        set_notify(client, admin, 0)  # "get ready" off
        walk_in(client, desk, doctor, "Abebe")
        walk_in(client, desk, doctor, "Kebede", "0911000002")
        patient = register(client, desk)
        link_directly(patient["id"], "DE482731")
        client.post("/queue/check-in", headers=desk, json={"doctor_id": doctor_id(doctor), "patient_id": patient["id"]})
        client.post(f"/queue/{doctor_id(doctor)}/call-next", headers=doctor)
        sent = events(bus, "queue.updated")
        almaz = [(e["ahead"], e["notify"], e["seq"]) for e in sent if e["patient_name"] == "Almaz Tefera"]
        assert almaz == [(2, None, 1), (1, None, 2)]
        # Walk-ins: only the turn SMS (near is off).
        assert [(e["patient_name"], e["notify"]) for e in sent if e["dedan_id"] is None] == [("Abebe", "turn")]

    def test_the_setting(self, client, admin, bus):
        from app import eventbus

        eventbus.publish_pending(bus)
        before = len(bus.xrange("endod:hospital"))
        set_notify(client, admin, 5)
        assert client.get("/hospital", headers=admin).json()["queue_notify_ahead"] == 5
        for bad in (-1, 21, "x"):
            assert client.patch("/hospital", headers=admin, json={"queue_notify_ahead": bad}).status_code == 422
        eventbus.publish_pending(bus)
        assert len(bus.xrange("endod:hospital")) == before  # not a listing change


class TestNear:
    def test_never_at_check_in_and_once_when_the_count_comes_down(self, client, admin, desk, doctor, bus):
        set_notify(client, admin, 2)
        for name, phone in (("Abebe", "0911000001"), ("Kebede", "0911000002"), ("Chaltu", "0911000003"),
                            ("Desta", "0911000004")):
            walk_in(client, desk, doctor, name, phone)
        assert [e["notify"] for e in events(bus, "queue.updated")] == []  # nothing at check-in
        ids = {e["patient_name"]: e["id"] for e in queue_of(client, desk, doctor)["entries"]}
        call_next = f"/queue/{doctor_id(doctor)}/call-next"
        client.post(call_next, headers=doctor)  # Abebe: Desta now has 2 ahead
        client.post(f"/queue/entries/{ids['Abebe']}/done", headers=doctor)
        client.post(call_next, headers=doctor)  # Kebede: Desta 1 ahead (no second near)
        sent = [(e["patient_name"], e["notify"]) for e in events(bus, "queue.updated") if e["notify"]]
        assert sent == [("Abebe", "turn"), ("Desta", "near"), ("Kebede", "turn")]


def _yesterday_queue(hospital, doctor, names):
    """Entries checked in yesterday (hospital time), still waiting."""
    from app import queues
    from app.db import platform_session

    with platform_session() as session:
        queue = queues.lock_queue(session, hospital, doctor_id(doctor), today() - timedelta(days=1))
        for name in names:
            queues.check_in(session, queue, patient_name=name, phone="+251911000009", dedan_id=None,
                            patient_id=None, booking_id=None, staff_id=None)
        return queue.id


class TestMidnight:
    def test_call_next_takes_yesterdays_leftovers_first(self, client, desk, doctor, hospital):
        walk_in(client, desk, doctor, "Today One")
        _yesterday_queue(hospital, doctor, ["Late Two", "Late One"])
        board = queue_of(client, desk, doctor)
        assert [(e["patient_name"], e["ticket"], e["status"]) for e in board["leftovers"]] == [
            ("Late Two", 1, "waiting"), ("Late One", 2, "waiting")]
        assert board["leftovers"][0]["day"] == (today() - timedelta(days=1)).isoformat()
        assert board["waiting"] == 3

        call_next = f"/queue/{doctor_id(doctor)}/call-next"
        order = []
        for _ in range(3):
            resp = client.post(call_next, headers=doctor)
            assert resp.status_code == 200, resp.text
            called = resp.json()["called"]
            order.append(called["patient_name"])
            assert client.post(call_next, headers=doctor).status_code == 409  # still called
            client.post(f"/queue/entries/{called['id']}/done", headers=doctor)
        assert order == ["Late Two", "Late One", "Today One"]
        assert queue_of(client, desk, doctor)["leftovers"] == []

    def test_the_worker_cancels_stale_entries(self, client, desk, doctor, hospital, bus):
        from app import queues
        from app.db import platform_session
        from app.models import QueueEntry
        from history_support import ZONE

        patient = register(client, desk)
        link_directly(patient["id"], "DE482731")
        queue_id = _yesterday_queue(hospital, doctor, ["Late One"])
        with platform_session() as session:
            queue = queues.lock_queue(session, hospital, doctor_id(doctor), today() - timedelta(days=1))
            queues.check_in(session, queue, patient_name="Almaz Tefera", phone=None, dedan_id="DE482731",
                            patient_id=patient["id"], booking_id=None, staff_id=None)
        walk_in(client, desk, doctor, "Today One")
        events(bus)  # what was sent so far
        bus.delete("endod:hospital")

        ended = datetime.combine(today(), datetime.min.time(), ZONE)  # yesterday's day ended at midnight
        with platform_session() as session:
            assert queues.cancel_stale(session, (ended + timedelta(hours=11)).astimezone(timezone.utc)) == 0
        with platform_session() as session:
            assert queues.cancel_stale(session, (ended + timedelta(hours=12, minutes=1)).astimezone(timezone.utc)) == 2
        with platform_session() as session:
            from sqlalchemy import select
            statuses = {e.patient_name: e.status for e in session.scalars(select(QueueEntry))}
        assert statuses == {"Late One": "cancelled", "Almaz Tefera": "cancelled", "Today One": "waiting"}
        sent = events(bus, "queue.updated")
        assert [(e["patient_name"], e["status"], e["dedan_id"]) for e in sent] == [
            ("Almaz Tefera", "cancelled", "DE482731")]
        assert queue_of(client, desk, doctor)["leftovers"] == []
        assert queue_id
