"""Endod's service fee and charges (docs/integrations.md "Charges"): the fee
settings from the platform (``fees.updated``, newest version kept, a default
before any), charges through the integration API (scopes, totals and rounding
in santim, idempotency, test mode, another hospital's charge not found, events
to the platform, webhooks, audit), bookings carrying the fee and marked paid
at the hospital."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from conftest import make_hospital
from test_integrations import (  # noqa: F401  (fixtures)
    API, admin, book, client, connected, count, fresh_limits, get_token, make_patient,
)

from app import bookings, fees
from app.db import platform_session
from app.models import AuditEvent, Booking, Charge, EndodFeeSettings, OutboxEvent, WebhookDelivery

SCOPES = ["charges.write", "bookings.write", "bookings.read", "webhooks"]
HOOK = "https://hooks.example.com/endod"
LAB = {"category": "lab_test", "code": "CBC", "name": "Complete blood count", "amount": "350.00", "quantity": 1}
XRAY = {"category": "imaging", "code": "XR-CHEST", "name": "Chest X-ray", "amount": "450", "quantity": 1}


@pytest.fixture
def live(client, admin):
    return connected(client, admin, scopes=SCOPES, webhook_url=HOOK, name="EMR")


@pytest.fixture
def auth(client, live):
    return get_token(client, live)


@pytest.fixture
def test_auth(client, admin):
    return get_token(client, connected(client, admin, scopes=SCOPES, mode="test", webhook_url=HOOK,
                                       name="EMR test"))


@pytest.fixture
def linked(hospital):
    return make_patient(hospital, mrn="SPH-000001", dedan_id="DE482731")


@pytest.fixture
def walk_in(hospital):
    return make_patient(hospital, mrn="SPH-000002", name="Abebe Kebede")


def set_fee(version=1, enabled=True, flat=2500, bp=0):
    with platform_session() as session:
        fees.on_fees_updated(session, {"version": version, "enabled": enabled, "flat_santim": flat,
                                       "percent_bp": bp, "currency": "ETB",
                                       "updated_at": "2026-11-03T08:00:00+00:00"})


def outbox(kind=None):
    with platform_session() as session:
        rows = session.scalars(select(OutboxEvent).order_by(OutboxEvent.created_at, OutboxEvent.id)).all()
        return [(r.type, json.loads(r.payload)) for r in rows if kind is None or r.type == kind]


def deliveries(event_type=None):
    with platform_session() as session:
        rows = session.scalars(select(WebhookDelivery).order_by(WebhookDelivery.created_at)).all()
        return [r.event_type for r in rows if event_type is None or r.event_type == event_type]


def audits(action):
    with platform_session() as session:
        return [json.loads(r.detail or "{}") for r in session.scalars(select(AuditEvent).where(
            AuditEvent.action == action))]


def charge(client, auth, mrn="SPH-000001", items=None, headers=None, **extra):
    return client.post(f"{API}/charges", headers={**auth, **(headers or {})},
                       json={"mrn": mrn, "items": items or [LAB], **extra})


# --- the fee settings ------------------------------------------------------------------------------------

class TestFeeSettings:
    def test_before_the_platform_says_anything_the_default_is_25_birr(self, db, monkeypatch):
        with platform_session() as session:
            fee = fees.current(session)
        assert (fee.enabled, fee.flat_santim, fee.percent_bp, fee.version) == (True, 2500, 0, 0)
        assert fees.fee_for(20_000, fee) == 2500  # 200 ETB -> 225 ETB
        monkeypatch.setenv("HOSPITAL_DEFAULT_SERVICE_FEE_SANTIM", "1000")
        assert fees.default().flat_santim == 1000

    def test_the_newest_version_is_kept(self, db):
        set_fee(version=3, flat=3000)
        set_fee(version=2, flat=100)  # late: ignored
        with platform_session() as session:
            fee = fees.current(session)
        assert (fee.flat_santim, fee.version) == (3000, 3)
        set_fee(version=3, flat=3000, bp=150)  # the periodic re-send of the same version
        set_fee(version=4, enabled=False, flat=0)
        with platform_session() as session:
            assert fees.current(session).enabled is False
            assert session.scalar(select(EndodFeeSettings.version)) == 4

    def test_the_rule_rounds_half_up_to_the_santim(self):
        fee = fees.Fee(enabled=True, flat_santim=1000, percent_bp=150, version=1)
        assert [fees.fee_for(s, fee) for s in (333, 300, 299, 0)] == [1005, 1005, 1004, 0]
        assert fees.fee_for(20_000, fees.Fee(False, 1000, 150, 2)) == 0

    @pytest.mark.parametrize("bad", [{"version": "1"}, {"flat_santim": -1}, {"percent_bp": 2001},
                                     {"currency": "USD"}, {"updated_at": "2026-11-03T08:00:00"}])
    def test_malformed_updates_are_refused(self, db, bad):
        from app.eventbus import PermanentEventError

        payload = {"version": 1, "enabled": True, "flat_santim": 2500, "percent_bp": 0, **bad}
        with pytest.raises(PermanentEventError):
            with platform_session() as session:
                fees.on_fees_updated(session, payload)

    def test_the_worker_handles_fees_updated(self):
        from app import worker

        assert worker.handlers()["fees.updated"] is fees.on_fees_updated

    def test_the_api_shows_the_fee_in_force(self, client, auth):
        set_fee(version=5, flat=2500, bp=100)
        body = client.get(f"{API}/service-fee", headers=auth).json()
        assert body["flat"] == "25.00" and body["percent"] == "1.00" and body["enabled"] is True
        assert body["example"] == {"subtotal": "200.00", "service_fee": "27.00", "total": "227.00"}


# --- charges ---------------------------------------------------------------------------------------------

class TestCharges:
    def test_a_charge_adds_one_fee_and_reaches_the_patient_and_the_webhooks(self, client, auth, live, linked):
        set_fee(version=7, flat=2500)
        resp = charge(client, auth, items=[LAB, {**XRAY, "quantity": 2}])
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # 350 + 2 x 450 = 1250 birr; one fee for the charge.
        assert (body["subtotal"], body["service_fee"], body["total"]) == ("1250.00", "25.00", "1275.00")
        assert body["fee"] == {"version": 7, "flat": "25.00", "percent": "0.00"}
        assert body["status"] == "open" and body["endod_id"] == "DE482731" and body["mrn"] == "SPH-000001"
        assert [i["line_total"] for i in body["items"]] == ["350.00", "900.00"]
        [(kind, event)] = outbox("charge.created")
        assert event["charge_id"] == body["id"] and event["dedan_id"] == "DE482731"
        assert (event["subtotal"], event["service_fee"], event["total"]) == (125_000, 2500, 127_500)
        assert event["items"][1] == {"category": "imaging", "code": "XR-CHEST", "name": "Chest X-ray",
                                     "amount": 45_000, "quantity": 2}
        assert deliveries() == ["charge.created"]
        [row] = audits("charge_created")
        assert row["via"] == "integration" and row["client_id"] == live["connection"]["client_id"]
        assert row["total"] == "1275.00" and "Complete blood count" not in json.dumps(row)
        # The items are encrypted at rest; the webhook never carries them.
        with platform_session() as session:
            stored = session.execute(select(Charge.items)).scalar()
            delivery = session.scalars(select(WebhookDelivery)).one()
        assert "Complete blood count" not in stored
        assert "Complete blood count" not in delivery.body

    def test_a_percentage_is_rounded_to_the_santim(self, client, auth, linked):
        set_fee(version=2, flat=1000, bp=150)
        body = charge(client, auth, items=[{**LAB, "amount": "3.33"}]).json()
        assert (body["subtotal"], body["service_fee"], body["total"]) == ("3.33", "10.05", "13.38")

    def test_no_fee_while_switched_off(self, client, auth, linked):
        set_fee(version=2, enabled=False, flat=0)
        body = charge(client, auth).json()
        assert (body["service_fee"], body["total"]) == ("0.00", "350.00")

    def test_a_patient_not_linked_to_endod_is_charged_too_but_gets_no_bill(self, client, auth, walk_in):
        body = charge(client, auth, mrn="SPH-000002").json()
        assert body["endod_id"] is None and body["service_fee"] == "25.00"
        assert outbox("charge.created") == []  # no app to show it in
        assert deliveries() == ["charge.created"]

    @pytest.mark.parametrize("items,status", [
        ([], 422), ([{**LAB, "amount": "0"}], 422), ([{**LAB, "amount": "12.345"}], 422),
        ([{**LAB, "quantity": 0}], 422), ([{**LAB, "category": "massage"}], 422), ([{**LAB, "code": "../x"}], 422),
        ([{**LAB, "extra": 1}], 422), ([LAB] * 101, 422),
    ])
    def test_items_are_checked(self, client, auth, linked, items, status):
        resp = client.post(f"{API}/charges", headers=auth, json={"mrn": "SPH-000001", "items": items})
        assert resp.status_code == status, resp.text
        assert resp.json()["resourceType"] == "OperationOutcome"
        assert count(Charge) == 0

    def test_scopes(self, client, admin, linked):
        reader = get_token(client, connected(client, admin, scopes=["charges.read"], name="Reader"))
        booker = get_token(client, connected(client, admin, scopes=["bookings.read"], name="Booker"))
        assert charge(client, reader).status_code == 403
        assert client.get(f"{API}/charges", headers=reader).status_code == 200
        assert client.get(f"{API}/charges", headers=booker).status_code == 403
        assert client.get(f"{API}/service-fee", headers=booker).status_code == 200
        assert client.get(f"{API}/charges").status_code == 401

    def test_idempotency_key(self, client, auth, linked):
        key = {"Idempotency-Key": "charge-0001"}
        first = charge(client, auth, headers=key)
        again = charge(client, auth, headers=key)
        assert again.status_code == 201 and again.headers.get("Idempotent-Replayed") == "true"
        assert again.json()["id"] == first.json()["id"] and count(Charge) == 1
        other = charge(client, auth, headers=key, items=[XRAY])
        assert other.status_code == 422
        assert len(outbox("charge.created")) == 1

    def test_paid_at_the_hospital_the_fee_is_owed_to_endod(self, client, auth, linked):
        cid = charge(client, auth).json()["id"]
        resp = client.post(f"{API}/charges/{cid}/paid", headers=auth,
                           json={"method": "mobile_money", "reference": "TB7781234"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "paid" and body["fee_owed_to_endod"] == "25.00" and body["paid_at"]
        [(kind, event)] = outbox("charge.paid")
        assert event["method"] == "mobile_money" and event["reference"] == "TB7781234"
        assert (event["subtotal"], event["service_fee"], event["total"]) == (35_000, 2500, 37_500)
        assert "items" not in event
        # The same again changes nothing; another way, or voiding it, is refused.
        assert client.post(f"{API}/charges/{cid}/paid", headers=auth,
                           json={"method": "mobile_money"}).status_code == 200
        assert client.post(f"{API}/charges/{cid}/paid", headers=auth, json={"method": "cash"}).status_code == 409
        assert client.post(f"{API}/charges/{cid}/void", headers=auth, json={"reason": "Oops"}).status_code == 409
        assert len(outbox("charge.paid")) == 1
        assert deliveries() == ["charge.created", "charge.paid"]
        assert audits("charge_paid")[0]["fee_owed_to_endod"] == "25.00"

    def test_an_unlinked_patients_payment_still_reaches_endods_ledger(self, client, auth, walk_in):
        cid = charge(client, auth, mrn="SPH-000002").json()["id"]
        client.post(f"{API}/charges/{cid}/paid", headers=auth, json={"method": "cash"})
        [(kind, event)] = outbox("charge.paid")
        assert event["dedan_id"] is None and event["service_fee"] == 2500

    def test_paid_at_is_checked(self, client, auth, linked):
        cid = charge(client, auth).json()["id"]
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        assert client.post(f"{API}/charges/{cid}/paid", headers=auth,
                           json={"method": "cash", "paid_at": future}).status_code == 400
        assert client.post(f"{API}/charges/{cid}/paid", headers=auth,
                           json={"method": "cash", "paid_at": "2026-11-03T09:00:00"}).status_code == 422
        assert client.post(f"{API}/charges/{cid}/paid", headers=auth, json={"method": "gold"}).status_code == 422

    def test_void_an_open_charge(self, client, auth, hospital, linked):
        cid = charge(client, auth).json()["id"]
        resp = client.post(f"{API}/charges/{cid}/void", headers=auth, json={"reason": "Entered twice."})
        assert resp.status_code == 200 and resp.json()["status"] == "voided"
        assert resp.json()["void_reason"] == "Entered twice."
        assert outbox("charge.voided") == [("charge.voided", {"charge_id": cid, "hospital_id": hospital,
                                                              "dedan_id": "DE482731"})]
        assert client.post(f"{API}/charges/{cid}/paid", headers=auth, json={"method": "cash"}).status_code == 409
        assert deliveries() == ["charge.created", "charge.voided"]

    def test_read_and_list(self, client, auth, linked, walk_in):
        first = charge(client, auth).json()["id"]
        second = charge(client, auth, mrn="SPH-000002", items=[XRAY]).json()["id"]
        client.post(f"{API}/charges/{first}/paid", headers=auth, json={"method": "cash"})
        assert client.get(f"{API}/charges/{first}", headers=auth).json()["items"][0]["name"] == "Complete blood count"
        assert [c["id"] for c in client.get(f"{API}/charges", headers=auth).json()["items"]] == [second, first]
        assert [c["id"] for c in client.get(f"{API}/charges", headers=auth,
                                            params={"status": "paid"}).json()["items"]] == [first]
        assert [c["id"] for c in client.get(f"{API}/charges", headers=auth,
                                            params={"mrn": "sph-000002"}).json()["items"]] == [second]
        assert client.get(f"{API}/charges", headers=auth, params={"status": "lost"}).status_code == 400
        assert client.get(f"{API}/charges", headers=auth, params={"mrn": "SPH-404404"}).status_code == 404

    def test_another_hospitals_charge_and_patient_are_not_found(self, client, auth, admin, linked):
        other = make_hospital(code="BET", name="Bethel Hospital")
        make_patient(other, mrn="BET-000001")
        assert charge(client, auth, mrn="BET-000001").status_code == 404
        with platform_session() as session:
            from app.models import Patient

            theirs = session.scalar(select(Patient.id).where(Patient.mrn == "BET-000001"))
            row = Charge(hospital_id=other, patient_id=theirs, items="[]", subtotal=100, service_fee=2500,
                         total=2600, status="open")
            session.add(row)
            session.flush()
            their_charge = row.id
        assert client.get(f"{API}/charges/{their_charge}", headers=auth).status_code == 404
        assert client.post(f"{API}/charges/{their_charge}/paid", headers=auth,
                           json={"method": "cash"}).status_code == 404
        assert client.post(f"{API}/charges/{their_charge}/void", headers=auth,
                           json={"reason": "Not ours"}).status_code == 404
        assert their_charge not in json.dumps(client.get(f"{API}/charges", headers=auth).json())

    def test_a_charge_for_a_booking_must_be_the_patients(self, client, auth, hospital, linked, walk_in):
        booking = book(hospital, payment="at_hospital", service_fee=2500, total=17500,
                       patient={"dedan_id": "DE482731", "name": "Almaz Tefera", "phone": None})
        assert charge(client, auth, booking_id=booking).status_code == 201  # the booking's Endod ID
        assert charge(client, auth, mrn="SPH-000002", booking_id=booking).status_code == 409
        assert charge(client, auth, booking_id="nope").status_code == 404

    def test_test_connections_write_and_send_nothing(self, client, test_auth, linked):
        set_fee(version=9, flat=3000)
        before = (count(Charge), count(OutboxEvent), count(WebhookDelivery), count(AuditEvent))
        resp = charge(client, test_auth, mrn="SPH-404404")
        assert resp.status_code == 201 and resp.json()["sample"] is True
        assert resp.json()["service_fee"] == "30.00" and resp.json()["total"] == "380.00"
        assert charge(client, test_auth, items=[{**LAB, "amount": "-1"}]).status_code == 422
        sample = resp.json()["id"]
        assert client.post(f"{API}/charges/{sample}/paid", headers=test_auth,
                           json={"method": "cash"}).json()["status"] == "paid"
        assert client.post(f"{API}/charges/{sample}/void", headers=test_auth,
                           json={"reason": "Sample"}).json()["status"] == "voided"
        assert client.post(f"{API}/charges/other/paid", headers=test_auth,
                           json={"method": "cash"}).status_code == 404
        assert client.get(f"{API}/charges", headers=test_auth).json()["items"][0]["sample"] is True
        assert (count(Charge), count(OutboxEvent), count(WebhookDelivery), count(AuditEvent)) == before


# --- bookings with the fee --------------------------------------------------------------------------------

class TestBookingsWithTheFee:
    def test_a_booking_paid_at_the_hospital_tells_what_to_collect(self, client, auth, hospital):
        booking_id = book(hospital, payment="at_hospital", service_fee=2500, total=17500)
        body = client.get(f"{API}/bookings/{booking_id}", headers=auth).json()
        assert (body["price"], body["service_fee"], body["total"]) == ("150.00", "25.00", "175.00")
        assert body["collect_at_hospital"] == "175.00" and body["fee_owed_to_endod"] == "25.00"

    def test_an_online_or_older_booking(self, client, auth, hospital):
        online = book(hospital, service_fee=800, total=15800)
        older = book(hospital)  # sent before the fee existed
        body = client.get(f"{API}/bookings/{online}", headers=auth).json()
        assert body["collect_at_hospital"] == "0.00" and body["fee_owed_to_endod"] == "0.00"
        assert client.get(f"{API}/bookings/{older}", headers=auth).json()["service_fee"] == "0.00"

    def test_marked_paid_at_the_hospital_tells_endod_once(self, client, auth, hospital):
        booking_id = book(hospital, payment="at_hospital", service_fee=2500, total=17500)
        resp = client.post(f"{API}/bookings/{booking_id}/paid", headers=auth,
                           json={"method": "cash", "reference": "RCPT-9"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["paid_method"] == "cash" and resp.json()["paid_at"]
        [(kind, event)] = outbox("appointment.paid")
        with platform_session() as session:
            external = session.get(Booking, booking_id).external_id
        assert event["appointment_id"] == external and event["method"] == "cash" and event["reference"] == "RCPT-9"
        assert client.post(f"{API}/bookings/{booking_id}/paid", headers=auth,
                           json={"method": "cash"}).status_code == 200
        assert client.post(f"{API}/bookings/{booking_id}/paid", headers=auth,
                           json={"method": "card"}).status_code == 409
        assert len(outbox("appointment.paid")) == 1
        assert audits("booking_paid")[0]["via"] == "integration"

    def test_an_online_booking_cannot_be_marked_paid_here(self, client, auth, hospital):
        booking_id = book(hospital)
        assert client.post(f"{API}/bookings/{booking_id}/paid", headers=auth,
                           json={"method": "cash"}).status_code == 409
        assert outbox("appointment.paid") == []

    def test_older_requests_without_the_fee_are_accepted(self, hospital):
        booking_id = book(hospital, payment="at_hospital")
        with platform_session() as session:
            assert session.get(Booking, booking_id).service_fee == 0

    def test_a_fee_sent_as_birr_is_refused(self, hospital):
        from app.eventbus import PermanentEventError  # noqa: F401

        before = count(Booking)
        book(hospital, payment="at_hospital", service_fee=25.0)  # not santim: refused (rejected back)
        assert count(Booking) == before
        assert outbox("appointment.rejected")

    def test_test_connections_try_it_on_a_sample(self, client, test_auth):
        rows = client.get(f"{API}/bookings", headers=test_auth).json()["items"]
        at_hospital = next(b for b in rows if b["payment"] == "at_hospital" and b["status"] == "confirmed")
        before = count(OutboxEvent)
        resp = client.post(f"{API}/bookings/{at_hospital['id']}/paid", headers=test_auth, json={"method": "cash"})
        assert resp.status_code == 200 and resp.json()["sample"] is True
        assert count(OutboxEvent) == before

    def test_the_rule_on_the_booking(self, hospital):
        booking_id = book(hospital, payment="at_hospital", service_fee=2500)
        with platform_session() as session:
            booking = session.get(Booking, booking_id)
            booking.status = "cancelled"
            with pytest.raises(bookings.BookingError):
                bookings.mark_paid(session, booking, "cash", None, None)
