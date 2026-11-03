"""The developer dashboard (Endod as an integration layer): who signs in
(administrators and developers only), the team, the playground's own Test
connection, the price list API, and video visits switched off."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from conftest import PASSWORD, bearer, make_hospital, make_staff, sign_in
from test_integrations import (  # noqa: F401  (fixtures)
    API, admin, basic, client, connected, fresh_limits, get_token, set_status, token_request,
)

from app import auth as auth_module, listing
from app.api import playground
from app.db import platform_session
from app.models import (
    ApplicationStatus, AuditEvent, Booking, Hospital, IntegrationClient, OutboxEvent, PriceItem, StaffUser,
)

CLINICAL = ["doctor", "nurse", "reception", "pharmacist", "billing", "records"]


@pytest.fixture(autouse=True)
def fresh_playground_limit():
    playground.CREDENTIALS_PER_HOSPITAL.reset()
    yield
    playground.CREDENTIALS_PER_HOSPITAL.reset()


@pytest.fixture
def developer(client, hospital):
    make_staff(hospital, "dev@sph.example", role="developer")
    return sign_in(client, "dev@sph.example", fresh=True)


def outbox(kind):
    with platform_session() as session:
        rows = session.scalars(select(OutboxEvent).order_by(OutboxEvent.created_at, OutboxEvent.id)).all()
        return [json.loads(r.payload) for r in rows if r.type == kind]


def audits(action):
    with platform_session() as session:
        return [json.loads(a.detail) if a.detail else {} for a in session.scalars(
            select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.at, AuditEvent.id))]


# --- who signs in ---------------------------------------------------------------------------------------------

class TestSignIn:
    @pytest.mark.parametrize("role", CLINICAL)
    def test_clinical_roles_are_refused_with_a_clear_message(self, client, hospital, role):
        make_staff(hospital, f"{role}@sph.example", role=role)
        resp = client.post("/auth/login", json={"email": f"{role}@sph.example", "password": PASSWORD})
        assert resp.status_code == 403
        assert resp.json()["error"] == auth_module.ROLE_NOT_ALLOWED
        assert "administrators and developers" in resp.json()["error"]
        assert audits("staff_sign_in_refused")[-1] == {"role": role}

    def test_a_wrong_password_never_tells_the_role(self, client, hospital):
        make_staff(hospital, "nurse@sph.example", role="nurse")
        resp = client.post("/auth/login", json={"email": "nurse@sph.example", "password": "Wrong-password-1"})
        assert resp.status_code == 401 and resp.json()["error"] == auth_module.INVALID_LOGIN

    @pytest.mark.parametrize("role", ["admin", "developer"])
    def test_admins_and_developers_sign_in(self, client, hospital, role):
        make_staff(hospital, f"{role}@sph.example", role=role)
        headers = sign_in(client, f"{role}@sph.example")
        assert client.get("/hospital", headers=headers).status_code == 200

    def test_a_clinical_session_opened_before_is_refused_everywhere(self, client, hospital, monkeypatch):
        make_staff(hospital, "nurse@sph.example", role="nurse")
        monkeypatch.setenv("HOSPITAL_CLINICAL_SIGN_IN_ENABLED", "true")
        headers = sign_in(client, "nurse@sph.example")
        assert client.get("/hospital", headers=headers).status_code == 200
        monkeypatch.setenv("HOSPITAL_CLINICAL_SIGN_IN_ENABLED", "false")
        for path in ("/hospital", "/patients", "/connections"):
            resp = client.get(path, headers=headers)
            assert resp.status_code == 403 and resp.json()["error"] == auth_module.ROLE_NOT_ALLOWED, path

    def test_developers_build_but_do_not_run_the_hospital(self, client, admin, developer):
        assert client.get("/connections", headers=developer).status_code == 200
        assert connected(client, developer, mode="test")["connection"]["mode"] == "test"
        assert client.get("/prices", headers=developer).status_code == 200
        assert client.get("/developer/guide", headers=developer).status_code == 200
        assert client.patch("/hospital", headers=developer, json={"city": "Adama"}).status_code == 403
        assert client.get("/staff", headers=developer).status_code == 403
        assert client.post("/staff", headers=developer, json={
            "email": "x@sph.example", "full_name": "X Y", "role": "developer"}).status_code == 403


# --- the team -------------------------------------------------------------------------------------------------

class TestTeam:
    def test_an_admin_invites_a_developer_with_a_temporary_password_and_two_step_verification(self, client, admin):
        resp = client.post("/staff", headers=admin, json={
            "email": "Selam@sph.example", "full_name": "Selam Bekele", "role": "developer"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["role"] == "developer" and body["must_change_password"] is True
        first = client.post("/auth/login", json={"email": "selam@sph.example", "password": body["temporary_password"]})
        assert first.status_code == 200 and first.json()["stage"] == "enroll"
        # The temporary password is changed first, then the authenticator is set up.
        assert client.get("/hospital", headers=bearer(first.json())).status_code == 403
        changed = client.post("/auth/password", headers=bearer(first.json()), json={
            "current_password": body["temporary_password"], "new_password": "Developer-pass-1"})
        assert changed.status_code == 200
        again = client.post("/auth/login", json={"email": "selam@sph.example", "password": "Developer-pass-1"})
        assert again.json()["stage"] == "enroll"
        assert client.get("/hospital", headers=bearer(again.json())).status_code == 403
        headers = sign_in(client, "selam@sph.example", "Developer-pass-1")
        assert client.get("/connections", headers=headers).status_code == 200

    def test_an_admin_invites_another_admin_and_removes_a_developer(self, client, admin, hospital):
        created = client.post("/staff", headers=admin, json={
            "email": "admin2@sph.example", "full_name": "Second Admin", "role": "admin"})
        assert created.status_code == 201 and created.json()["role"] == "admin"
        dev_id = make_staff(hospital, "dev@sph.example", role="developer")
        developer = sign_in(client, "dev@sph.example")
        team = client.get("/staff", headers=admin).json()
        assert {"admin@sph.example", "admin2@sph.example", "dev@sph.example"} <= {s["email"] for s in team}
        removed = client.patch(f"/staff/{dev_id}", headers=admin, json={"active": False})
        assert removed.status_code == 200 and removed.json()["active"] is False
        assert client.get("/auth/me", headers=developer).status_code == 401
        refused = client.post("/auth/login", json={"email": "dev@sph.example", "password": PASSWORD})
        assert refused.status_code == 401


# --- the playground's connection ---------------------------------------------------------------------------------

class TestPlayground:
    def test_credentials_are_a_hidden_test_connection(self, client, admin, hospital):
        first = client.post("/playground/credentials", headers=admin, json={})
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["client_id"].startswith("endod_test_") and body["mode"] == "test"
        assert "webhooks" not in body["scopes"] and "prices.write" in body["scopes"]
        with platform_session() as session:
            rows = session.scalars(select(IntegrationClient).where(IntegrationClient.hospital_id == hospital)).all()
            assert len(rows) == 1 and rows[0].playground is True and rows[0].mode == "test"
            assert rows[0].secret_hash != body["client_secret"] and rows[0].webhook_url is None
            pk = rows[0].id
        # Never listed, shown or changed by staff.
        assert client.get("/connections", headers=admin).json()["items"] == []
        assert client.get(f"/connections/{pk}", headers=admin).status_code == 404
        for action in ("rotate-secret", "disconnect", "webhook/test"):
            assert client.post(f"/connections/{pk}/{action}", headers=admin, json={}).status_code == 404, action
        assert client.post(f"/connections/{pk}/ip-restriction", headers=admin,
                           json={"allowed_ips": ["10.0.0.1"]}).status_code == 404
        assert client.get(f"/connections/{pk}/requests", headers=admin).status_code == 404

    def test_each_call_rotates_the_secret_of_the_same_connection(self, client, admin):
        first = client.post("/playground/credentials", headers=admin, json={}).json()
        token = get_token(client, {"connection": {"client_id": first["client_id"]}, "client_secret": first["client_secret"]})
        assert client.get(f"{API}/bookings", headers=token).json()["items"][0]["sample"] is True
        second = client.post("/playground/credentials", headers=admin, json={}).json()
        assert second["client_id"] == first["client_id"] and second["client_secret"] != first["client_secret"]
        # The old secret stops working; a token issued with it stays valid until it expires, so
        # dashboard servers renewing at the same time never revoke each other's tokens.
        old = token_request(client, headers=basic(first["client_id"], first["client_secret"]))
        assert old.status_code == 401
        assert client.get(f"{API}/bookings", headers=token).status_code == 200
        newer = get_token(client, {"connection": {"client_id": second["client_id"]},
                                   "client_secret": second["client_secret"]})
        assert client.get(f"{API}/bookings", headers=newer).status_code == 200
        assert audits("integration_playground_credentials")[-1] == {"client_id": first["client_id"]}

    def test_test_mode_only_never_real_data(self, client, admin, hospital):
        with platform_session() as session:
            session.add(Booking(hospital_id=hospital, external_id="real-1", patient_dedan_id="DE123456",
                                patient_name="Real Patient", visit_mode="in_person",
                                scheduled_at=datetime.now(timezone.utc) + timedelta(days=1), status="confirmed"))
        creds = client.post("/playground/credentials", headers=admin, json={}).json()
        token = get_token(client, {"connection": {"client_id": creds["client_id"]}, "client_secret": creds["client_secret"]})
        items = client.get(f"{API}/bookings", headers=token).json()["items"]
        assert items and all(b["sample"] for b in items) and "Real Patient" not in json.dumps(items)
        put = client.put(f"{API}/prices/consultation", headers=token, json={"in_person": "999.00"})
        assert put.status_code == 200 and put.json()["sample"] is True
        with platform_session() as session:
            assert session.get(Hospital, hospital).price_in_person is None

    def test_developers_may_use_it_but_not_pending_hospitals(self, client, developer, hospital):
        assert client.post("/playground/credentials", headers=developer, json={}).status_code == 200
        set_status(hospital, status="approved", application=ApplicationStatus.SUBMITTED)
        assert client.post("/playground/credentials", headers=developer, json={}).status_code == 403

    def test_rate_limited(self, client, admin):
        for _ in range(playground.CREDENTIALS_PER_HOSPITAL.limit):
            assert client.post("/playground/credentials", headers=admin, json={}).status_code == 200
        limited = client.post("/playground/credentials", headers=admin, json={})
        assert limited.status_code == 429 and limited.headers["Retry-After"]

    def test_staff_connections_do_not_count_it(self, client, admin, monkeypatch):
        from app.api import connections

        monkeypatch.setattr(connections, "MAX_CONNECTIONS", 1)
        client.post("/playground/credentials", headers=admin, json={})
        assert connected(client, admin, mode="test")["connection"]["mode"] == "test"


# --- the price list API --------------------------------------------------------------------------------------------

LABS = [{"code": "CBC", "name": "Complete blood count", "price": "350.00", "active": True},
        {"code": "MAL-RDT", "name": "Malaria rapid test", "price": 120, "active": True}]


@pytest.fixture
def prices(client, admin):
    return get_token(client, connected(client, admin, scopes=["prices.write"], name="Billing system"))


class TestPricing:
    def test_scopes(self, client, admin):
        reader = get_token(client, connected(client, admin, scopes=["prices.read"], name="Reader"))
        other = get_token(client, connected(client, admin, scopes=["bookings.read"], name="Other"))
        assert client.get(f"{API}/prices", headers=reader).status_code == 200
        assert client.put(f"{API}/prices/lab-tests", headers=reader, json={"items": LABS}).status_code == 403
        assert client.put(f"{API}/prices/consultation", headers=reader, json={"in_person": "100"}).status_code == 403
        assert client.get(f"{API}/prices", headers=other).status_code == 403

    def test_a_category_is_replaced_as_a_whole_and_idempotent(self, client, prices, hospital):
        first = client.put(f"{API}/prices/lab-tests", headers=prices, json={"items": LABS})
        assert first.status_code == 200, first.text
        body = first.json()
        assert (body["added"], body["updated"], body["removed"], body["unchanged"]) == (2, 0, 0, 0)
        assert [i["code"] for i in body["items"]] == ["CBC", "MAL-RDT"]
        assert body["items"][1]["price"] == "120.00" and body["category"] == "lab_tests"
        again = client.put(f"{API}/prices/lab-tests", headers=prices, json={"items": LABS}).json()
        assert (again["added"], again["updated"], again["removed"], again["unchanged"]) == (0, 0, 0, 2)
        changed = client.put(f"{API}/prices/lab-tests", headers=prices, json={"items": [
            {"code": "CBC", "name": "Complete blood count", "price": "400.50", "active": False},
            {"code": "HBA1C", "name": "HbA1c", "price": "600"}]}).json()
        assert (changed["added"], changed["updated"], changed["removed"], changed["unchanged"]) == (1, 1, 1, 0)
        assert {i["code"]: (i["price"], i["active"]) for i in changed["items"]} == {
            "CBC": ("400.50", False), "HBA1C": ("600.00", True)}
        # Other categories are untouched; GET has everything.
        client.put(f"{API}/prices/imaging", headers=prices, json={"items": [
            {"code": "XR-CHEST", "name": "Chest X-ray", "price": "450"}]})
        everything = client.get(f"{API}/prices", headers=prices).json()
        assert [i["code"] for i in everything["lab_tests"]] == ["CBC", "HBA1C"]
        assert [i["code"] for i in everything["imaging"]] == ["XR-CHEST"] and everything["procedures"] == []
        assert everything["currency"] == "ETB"
        cleared = client.put(f"{API}/prices/imaging", headers=prices, json={"items": []}).json()
        assert cleared["removed"] == 1 and cleared["items"] == []
        synced = audits("prices_synced")
        assert synced[0]["category"] == "lab_tests" and synced[0]["via"] == "integration"
        assert len(synced) == 4  # the unchanged repeat is not audited

    @pytest.mark.parametrize("items", [
        [LABS[0], LABS[0]],
        [{"code": "CBC", "name": "Complete blood count", "price": "1.005"}],
        [{"code": "CBC", "name": "Complete blood count", "price": "-1"}],
        [{"code": "bad code", "name": "Complete blood count", "price": "1"}],
        [{"code": "CBC", "name": "C", "price": "1"}],
        [{"code": "CBC", "name": "Complete blood count", "price": "1", "extra": True}],
    ])
    def test_invalid_lists_are_refused(self, client, prices, items):
        resp = client.put(f"{API}/prices/lab-tests", headers=prices, json={"items": items})
        assert resp.status_code == 422, resp.text
        assert resp.json()["resourceType"] == "OperationOutcome"
        with platform_session() as session:
            assert session.scalars(select(PriceItem)).all() == []

    def test_the_consultation_price_updates_the_listing(self, client, prices, hospital):
        with platform_session() as session:
            h = session.get(Hospital, hospital)
            h.latitude, h.longitude = 9.03, 38.74
        resp = client.put(f"{API}/prices/consultation", headers=prices, json={"in_person": "175.50"})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"currency": "ETB", "in_person": "175.50", "listed": True}
        with platform_session() as session:
            assert session.get(Hospital, hospital).price_in_person == 17550
        listed = outbox("hospital.listed")
        assert listed[-1]["price_in_person"] == 17550 and listed[-1]["hospital_id"] == hospital
        assert audits("hospital_updated")[-1]["to"] == "175.50"
        # The same price again: nothing to announce.
        client.put(f"{API}/prices/consultation", headers=prices, json={"in_person": "175.50"})
        assert len(outbox("hospital.listed")) == len(listed)
        assert client.put(f"{API}/prices/consultation", headers=prices, json={"in_person": "0"}).status_code == 422
        # The dashboard's Settings page reads the same list.
        assert client.get("/prices", headers=prices).status_code == 401  # an access token is no staff session

    def test_the_dashboard_reads_the_price_list(self, client, admin, prices):
        client.put(f"{API}/prices/lab-tests", headers=prices, json={"items": LABS})
        client.put(f"{API}/prices/consultation", headers=prices, json={"in_person": "150"})
        listed = client.get("/prices", headers=admin).json()
        assert listed["consultation"] == {"in_person": "150.00"}
        assert [i["code"] for i in listed["lab_tests"]] == ["CBC", "MAL-RDT"]

    def test_test_mode_writes_nothing(self, client, admin, hospital):
        test = get_token(client, connected(client, admin, scopes=["prices.write"], mode="test", name="Test"))
        resp = client.put(f"{API}/prices/lab-tests", headers=test, json={"items": LABS})
        assert resp.status_code == 200 and resp.json()["sample"] is True and resp.json()["added"] == 2
        assert client.put(f"{API}/prices/lab-tests", headers=test,
                          json={"items": [LABS[0], LABS[0]]}).status_code == 422  # checked as in Live
        assert client.get(f"{API}/prices", headers=test).json()["sample"] is True
        consult = client.put(f"{API}/prices/consultation", headers=test, json={"in_person": "120"})
        assert consult.json()["sample"] is True
        with platform_session() as session:
            assert session.scalars(select(PriceItem)).all() == []
            assert session.get(Hospital, hospital).price_in_person is None
        assert outbox("hospital.listed") == [] and audits("prices_synced") == []

    def test_another_hospitals_prices_are_never_seen(self, client, prices, hospital):
        client.put(f"{API}/prices/lab-tests", headers=prices, json={"items": LABS})
        other = make_hospital(code="BLH", name="Black Lion")
        make_staff(other, "admin@blh.example", role="admin")
        their_admin = sign_in(client, "admin@blh.example", fresh=True)
        theirs = get_token(client, connected(client, their_admin, scopes=["prices.write"]))
        assert client.get(f"{API}/prices", headers=theirs).json()["lab_tests"] == []
        client.put(f"{API}/prices/lab-tests", headers=theirs, json={"items": [LABS[0]]})
        assert [i["code"] for i in client.get(f"{API}/prices", headers=prices).json()["lab_tests"]] == ["CBC", "MAL-RDT"]
        with platform_session() as session:
            assert {(r.hospital_id, r.code) for r in session.scalars(select(PriceItem))} == {
                (hospital, "CBC"), (hospital, "MAL-RDT"), (other, "CBC")}


# --- video visits off -------------------------------------------------------------------------------------------

class TestVideoVisitsOff:
    def test_approve_and_decline_answer_404(self, client, admin):
        token = get_token(client, connected(client, admin, scopes=["bookings.write", "bookings.read"]))
        for action, body in (("approve", {"doctor_id": "c0ffee00c0ffee00c0ffee00c0ffee00"}), ("decline", {"reason": "No"})):
            resp = client.post(f"{API}/bookings/x/{action}", headers=token, json=body)
            assert resp.status_code == 404, (action, resp.text)
            # Even without a token: as if the endpoint did not exist.
            assert client.post(f"{API}/bookings/x/{action}", json=body).status_code == 404
        assert client.post(f"{API}/bookings/x/cancel", headers=token, json={"reason": "No longer"}).status_code == 404
        # Test bookings are in-person only.
        test = get_token(client, connected(client, admin, scopes=["bookings.read"], mode="test", name="Test bookings"))
        assert {b["visit_mode"] for b in client.get(f"{API}/bookings", headers=test).json()["items"]} == {"in_person"}

    @pytest.mark.video_visits
    def test_they_come_back_with_the_setting(self, client, admin):
        token = get_token(client, connected(client, admin, scopes=["bookings.write"]))
        resp = client.post(f"{API}/bookings/x/decline", headers=token, json={"reason": "No"})
        assert resp.status_code == 404 and "Booking not found" in resp.text

    def test_the_listing_never_offers_video(self, hospital, monkeypatch):
        with platform_session() as session:
            h = session.get(Hospital, hospital)
            h.video_enabled, h.price_video, h.price_in_person = True, 20000, 15000
            snapshot = listing.snapshot(h)
            assert snapshot["video_enabled"] is False and snapshot["price_video"] is None
            assert snapshot["price_in_person"] == 15000
            monkeypatch.setenv("HOSPITAL_VIDEO_VISITS_ENABLED", "true")
            on = listing.snapshot(h)
            assert on["video_enabled"] is True and on["price_video"] == 20000

    def test_a_video_booking_made_before_cannot_be_approved_or_joined(self, client, hospital, monkeypatch):
        from app import bookings as booking_rules
        from conftest import make_staff as staff

        doctor = staff(hospital, "doc@sph.example", role="doctor")
        with platform_session() as session:
            booking = Booking(hospital_id=hospital, external_id="video-1", patient_dedan_id="DE123456",
                              patient_name="Video Patient", visit_mode="video", status="awaiting_doctor",
                              scheduled_at=datetime.now(timezone.utc) + timedelta(days=1))
            session.add(booking)
            session.flush()
            with pytest.raises(booking_rules.BookingError) as refused:
                booking_rules.approve_video(session, booking, session.get(StaffUser, doctor), None)
            assert refused.value.status_code == 409 and "not offered" in str(refused.value)
            booking.status, booking.doctor_id, booking.meeting_room = "confirmed", doctor, "room-1"
            booking_id = booking.id
        monkeypatch.setenv("HOSPITAL_CLINICAL_SIGN_IN_ENABLED", "true")
        headers = sign_in(client, "doc@sph.example")
        joined = client.post(f"/bookings/{booking_id}/video", headers=headers)
        assert joined.status_code == 409 and "not offered" in joined.json()["error"]

    def test_settings_refuse_video(self, client, admin):
        assert client.get("/hospital", headers=admin).json()["video_visits_offered"] is False
        for body in ({"video_enabled": True}, {"price_video": "200"}):
            resp = client.patch("/hospital", headers=admin, json=body)
            assert resp.status_code == 400 and "Video visits" in resp.json()["error"]
        assert client.patch("/hospital", headers=admin, json={"price_in_person": "150"}).status_code == 200


def test_the_guide_is_served_to_the_dashboard(client, admin):
    body = client.get("/developer/guide", headers=admin).json()
    assert body["markdown"].startswith("# Endod Hospital Integration API")
    assert "## 9. Pricing" in body["markdown"] and body["openapi_url"].endswith("/openapi.json")
    assert client.get("/developer/guide").status_code == 401


def test_the_guide_hides_video_visits(client, admin):
    from app.api.integrations import GUIDE, _guide

    raw = GUIDE.read_text(encoding="utf-8")
    assert "approve or decline video" in raw  # kept, in a hidden block, to bring back
    assert "approve or decline video" not in _guide() and "<!--" not in _guide()


def test_the_developer_role():
    from app.models import Role

    assert Role.DASHBOARD == ("admin", "developer") and "developer" in Role.ALL
    assert len(Role.DEVELOPER) <= StaffUser.__table__.c.role.type.length
