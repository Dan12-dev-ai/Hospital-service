"""Hospital onboarding: the application wizard, documents, the demo booking,
the pending-hospital lockout, and Endod's review (platform API and CLI).

The calendar is pinned: "now" is Friday 23 October 2026, 16:00 in Addis Ababa
(13:00 UTC), unless a test moves it.
"""

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import fakeredis
import pytest

from conftest import make_staff, sign_in

PLATFORM_KEY = "platform-test-key"
ADDIS = ZoneInfo("Africa/Addis_Ababa")
FRIDAY_4PM_ADDIS = datetime(2026, 10, 23, 13, 0, tzinfo=timezone.utc)

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
KINDS = ("moh_license", "trade_license", "tin_certificate", "owner_id")

ACCOUNT = {"hospital_name": "Bethel Teaching Hospital", "facility_type": "hospital", "admin_name": "Selam Bekele",
           "admin_title": "Medical Director", "admin_phone": "0911 234 567", "admin_email": "selam@bethel.example",
           "password": "Strong-pass-123"}
FACILITY = {"facility_type": "hospital", "ownership": "private", "name": "Bethel Teaching Hospital",
            "name_am": "ቤቴል ሆስፒታል", "city": "Addis Ababa", "phone": "011 551 7611",
            "services": ["general_medicine", "pediatrics"], "open_hours": "Mon-Sat 08:00-17:00"}
LOCATION = {"address": "Gulele, near the stadium", "latitude": 9.0612, "longitude": 38.7321}


@pytest.fixture(autouse=True)
def pinned(monkeypatch):
    monkeypatch.setenv("HOSPITAL_PLATFORM_ADMIN_KEY", PLATFORM_KEY)
    from app import onboarding
    from app.api import onboarding as signup

    signup._signups.clear()
    monkeypatch.setattr(onboarding, "now", lambda: FRIDAY_4PM_ADDIS)


KEY = {"X-Platform-Key": PLATFORM_KEY}


@pytest.fixture
def bus():
    return fakeredis.FakeRedis(decode_responses=True)


def addis(day: int, hour: int, minute: int = 0, month: int = 10) -> str:
    return datetime(2026, month, day, hour, minute, tzinfo=ADDIS).isoformat()


_phones = iter(range(10_000_000, 99_999_999))


def apply(client, **change):
    """A new application (the account step). Each further hospital gets its own mobile."""
    if "admin_phone" not in change and change.get("admin_email", ACCOUNT["admin_email"]) != ACCOUNT["admin_email"]:
        change["admin_phone"] = f"09{next(_phones)}"
    resp = client.post("/onboarding", json={**ACCOUNT, **change})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["hospital"]["id"]


def upload(client, headers, kind, data=PDF, name="license.pdf"):
    return client.post(f"/onboarding/documents/{kind}", content=data,
                       headers={**headers, "X-Filename": name, "Content-Type": "application/octet-stream"})


def ready(client, **change):
    """A new application with its four documents: ready to book a demo."""
    headers, hospital_id = apply(client, **change)
    for kind in KINDS:
        assert upload(client, headers, kind).status_code == 201
    return headers, hospital_id


def complete(client, headers, demo_at=None):
    """Every step of the application, ready to submit."""
    assert client.patch("/onboarding/facility", headers=headers, json=FACILITY).status_code == 200
    assert client.patch("/onboarding/location", headers=headers, json=LOCATION).status_code == 200
    for kind in KINDS:
        assert upload(client, headers, kind).status_code == 201
    assert client.patch("/onboarding/documents", headers=headers, json={"license_number": "MOH/AA/1234"}).status_code == 200
    resp = client.post("/onboarding/demo", headers=headers, json={"demo_at": demo_at or addis(26, 10)})
    assert resp.status_code == 200, resp.text
    return resp.json()


def published(bus, event_type="onboarding.demo_booked"):
    from app import eventbus

    eventbus.publish_pending(bus)
    return [json.loads(f["payload"]) for _id, f in bus.xrange("endod:hospital") if f["type"] == event_type]


class TestWizard:
    def test_each_step_is_saved_and_the_wizard_resumes_where_it_stopped(self, client):
        headers, hospital_id = apply(client)
        app = client.get("/onboarding/application", headers=headers).json()
        assert app["status"] == "draft" and app["next_step"] == "facility"
        assert app["contact"] == {"full_name": "Selam Bekele", "title": "Medical Director",
                                  "phone": "+251911234567", "email": "selam@bethel.example"}
        assert set(app["missing"]["facility"]) == {"city", "phone", "open_hours", "services"}

        saved = client.patch("/onboarding/facility", headers=headers, json=FACILITY).json()
        assert saved["next_step"] == "location"
        assert saved["facility"]["ownership"] == "private" and saved["facility"]["name_am"] == "ቤቴል ሆስፒታል"
        assert client.patch("/onboarding/location", headers=headers, json=LOCATION).json()["next_step"] == "documents"
        for kind in KINDS[:3]:
            upload(client, headers, kind)
        # A new sign-in (or a reload) comes back to the same step.
        again = sign_in(client, "selam@bethel.example", "Strong-pass-123")
        app = client.get("/onboarding/application", headers=again).json()
        assert app["next_step"] == "documents" and app["missing"]["documents"] == ["owner_id", "license_number"]

    def test_contact_step_can_be_corrected(self, client):
        headers, _ = apply(client, admin_phone=None, admin_title=None)
        app = client.get("/onboarding/application", headers=headers).json()
        assert app["next_step"] == "contact" and set(app["missing"]["contact"]) == {"title", "phone"}
        assert client.patch("/onboarding/contact", headers=headers, json={
            "full_name": "Selam B.", "title": "Owner", "phone": "011 551 7611"}).status_code == 422  # not a mobile
        saved = client.patch("/onboarding/contact", headers=headers, json={
            "full_name": "Selam B.", "title": "Owner", "phone": "+251 711 234 567"}).json()
        assert saved["contact"]["phone"] == "+251711234567" and saved["next_step"] == "facility"

    @pytest.mark.parametrize("change", [
        {"facility_type": "pharmacy"}, {"ownership": "military"}, {"services": []}, {"services": ["astrology"]},
        {"phone": ""}, {"open_hours": ""}, {"city": " "},
    ])
    def test_invalid_facility(self, client, change):
        headers, _ = apply(client)
        assert client.patch("/onboarding/facility", headers=headers, json={**FACILITY, **change}).status_code == 422

    @pytest.mark.parametrize("change", [{"latitude": 91}, {"longitude": None}, {"address": ""}])
    def test_invalid_location(self, client, change):
        headers, _ = apply(client)
        assert client.patch("/onboarding/location", headers=headers, json={**LOCATION, **change}).status_code == 422

    def test_sign_up_validates_the_new_fields(self, client):
        assert client.post("/onboarding", json={**ACCOUNT, "facility_type": "spa"}).status_code == 400
        assert client.post("/onboarding", json={**ACCOUNT, "admin_phone": "12"}).status_code == 422

    def test_submit_needs_every_step_then_locks_the_application(self, client, bus):
        headers, _ = apply(client)
        refused = client.post("/onboarding/submit", headers=headers)
        assert refused.status_code == 400
        assert refused.json()["error"] == "Finish these steps first: facility, location, documents, demo booking."
        complete(client, headers)
        submitted = client.post("/onboarding/submit", headers=headers).json()
        assert submitted["status"] == "submitted" and submitted["submitted_at"]
        # Under review: the application is frozen, except the demo time.
        assert client.patch("/onboarding/facility", headers=headers, json=FACILITY).status_code == 409
        assert upload(client, headers, "owner_id").status_code == 409
        assert client.post("/onboarding/submit", headers=headers).status_code == 409
        moved = client.post("/onboarding/demo", headers=headers, json={"demo_at": addis(27, 14, 30)})
        assert moved.status_code == 200 and moved.json()["demo"]["demo_at"] == "2026-10-27T14:30:00+03:00"
        assert [p["changed"] for p in published(bus)] == [False, True]

    def test_a_hospital_that_signed_up_before_applications_existed(self, client):
        from sqlalchemy import delete

        from app.db import platform_session
        from app.models import OnboardingApplication

        headers, _ = apply(client)
        with platform_session() as session:
            session.execute(delete(OnboardingApplication))
        app = client.get("/onboarding/application", headers=headers).json()
        assert app["status"] == "draft" and app["contact"]["title"] is None
        assert client.patch("/onboarding/location", headers=headers, json=LOCATION).status_code == 200

    def test_only_the_admin_fills_in_the_application(self, client):
        _headers, hospital_id = apply(client)
        make_staff(hospital_id, "nurse@bethel.example", role="nurse")
        nurse = sign_in(client, "nurse@bethel.example")
        assert client.get("/onboarding/application", headers=nurse).status_code == 403
        assert upload(client, nurse, "owner_id").status_code == 403
        assert client.get("/onboarding/application").status_code == 401


class TestLockout:
    #: The routes a pending hospital may use (method, path).
    OPEN = {
        ("POST", "/auth/login"), ("POST", "/auth/logout"), ("GET", "/auth/me"), ("POST", "/auth/password"),
        ("POST", "/onboarding"), ("GET", "/health"),
    }

    def test_every_other_staff_route_refuses_a_pending_hospital(self, client):
        from app.main import create_app

        headers, _ = apply(client)
        checked = 0
        # Every route the service has (the OpenAPI document lists them all).
        for route, operations in create_app().openapi()["paths"].items():
            if route.startswith("/platform/"):
                continue
            for method in operations:
                method = method.upper()
                if (method, route) in self.OPEN or route.startswith("/onboarding/"):
                    continue
                path = re.sub(r"\{[^}]+\}", "0" * 32, route)
                resp = client.request(method, path, headers=headers, json={})
                assert resp.status_code == 403, (method, route, resp.status_code, resp.text)
                assert "not approved" in resp.json()["error"], (method, route)
                checked += 1
        assert checked > 40

    def test_onboarding_routes_stay_open_while_pending(self, client):
        headers, _ = apply(client)
        assert client.get("/onboarding/application", headers=headers).status_code == 200
        assert client.get("/onboarding/demo-slots", headers=headers).status_code == 200
        assert upload(client, headers, "owner_id").status_code == 201
        assert client.get("/onboarding/documents/owner_id", headers=headers).status_code == 200
        assert client.get("/auth/me", headers=headers).status_code == 200
        assert client.post("/auth/logout", headers=headers).status_code == 200
        assert client.get("/auth/me", headers=headers).status_code == 401

    def test_approval_opens_the_portal_and_closes_the_application(self, client, admin):
        headers, hospital_id = apply(client)
        complete(client, headers)
        client.post("/onboarding/submit", headers=headers)
        approved = client.post(f"/platform/hospitals/{hospital_id}/approve", headers=KEY).json()
        assert approved["status"] == "approved"
        assert client.get("/hospital", headers=headers).status_code == 200
        assert client.get("/patients", headers=headers).status_code == 200
        app = client.get("/onboarding/application", headers=headers).json()
        assert app["status"] == "approved"
        assert client.patch("/onboarding/location", headers=headers, json=LOCATION).status_code == 409
        assert client.post("/onboarding/demo", headers=headers, json={"demo_at": addis(28, 9)}).status_code == 409
        # An approved hospital (the conftest one) is untouched by all this.
        assert client.get("/hospital", headers=admin).json()["status"] == "approved"

    def test_a_suspended_hospital_keeps_its_records(self, client, admin, hospital):
        client.post(f"/platform/hospitals/{hospital}/suspend", headers=KEY)
        assert client.get("/patients", headers=admin).status_code == 200


class TestDocuments:
    def test_upload_replace_and_view(self, client, tmp_path):
        from app import files

        headers, hospital_id = apply(client)
        first = upload(client, headers, "moh_license", PDF, "moh license.pdf").json()
        item = first["documents"]["items"][0]
        assert item["uploaded"] and item["filename"] == "moh license.pdf" and item["content_type"] == "application/pdf"
        old_files = set((tmp_path / "files" / hospital_id).iterdir())
        assert len(old_files) == 1

        replaced = upload(client, headers, "moh_license", PNG, "scan.png").json()["documents"]["items"][0]
        assert replaced["content_type"] == "image/png" and replaced["filename"] == "scan.png"
        now_files = set((tmp_path / "files" / hospital_id).iterdir())
        assert len(now_files) == 1 and now_files != old_files  # the old file is gone

        view = client.get("/onboarding/documents/moh_license", headers=headers)
        assert view.status_code == 200 and view.content == PNG
        assert view.headers["content-type"] == "image/png" and view.headers["x-content-type-options"] == "nosniff"
        stored = files.path_for(hospital_id, next(iter(now_files)).name).read_bytes()
        assert stored.startswith(b"ENDODENC") and PNG not in stored  # encrypted at rest (app/crypto.py)

    @pytest.mark.parametrize("data,name,status", [
        (b"just text, not a document", "notes.pdf", 415),
        (b"MZ\x90\x00" + b"\x00" * 32, "tool.exe", 415),
        (PDF, "license.png", 400),  # the name says PNG, the content says PDF
        (b"", "empty.pdf", 400),
        (PDF + b"\x00" * (10 * 1024 * 1024), "huge.pdf", 413),
    ], ids=["text", "exe", "name-mismatch", "empty", "too-large"])
    def test_documents_are_checked(self, client, tmp_path, data, name, status):
        headers, hospital_id = apply(client)
        assert upload(client, headers, "tin_certificate", data, name).status_code == status
        folder = tmp_path / "files" / hospital_id
        assert not folder.exists() or list(folder.iterdir()) == []  # nothing left behind

    @pytest.mark.parametrize("kind", ["passport", "moh_license.pdf", "%2e%2e", "MOH_LICENSE"])
    def test_unknown_kinds(self, client, kind):
        headers, _ = apply(client)
        assert upload(client, headers, kind).status_code == 404
        assert client.get(f"/onboarding/documents/{kind}", headers=headers).status_code == 404

    def test_a_hospital_sees_only_its_own_documents(self, client):
        mine, _ = apply(client)
        upload(client, mine, "owner_id", PDF, "my-id.pdf")
        other, _ = apply(client, admin_email="other@clinic.example", hospital_name="Other Clinic")
        assert client.get("/onboarding/documents/owner_id", headers=other).status_code == 404

    def test_removing_a_pending_sign_up_deletes_its_files(self, client, tmp_path):
        headers, hospital_id = apply(client)
        upload(client, headers, "owner_id")
        assert client.delete(f"/platform/hospitals/{hospital_id}", headers=KEY).status_code == 200
        assert list((tmp_path / "files" / hospital_id).iterdir()) == []


class TestDemo:
    def test_the_calendar_is_weekdays_9_to_5_addis_time_from_tomorrow_for_30_days(self, client):
        headers, _ = apply(client)
        body = client.get("/onboarding/demo-slots", headers=headers).json()
        assert body["timezone"] == "Africa/Addis_Ababa" and body["minutes"] == 30 and body["current"] is None
        days = body["days"]
        # Friday afternoon: the next day on offer is Monday; the last is Friday 20 November.
        assert days[0]["date"] == "2026-10-26" and days[-1]["date"] == "2026-11-20"
        assert len(days) == 20 and all(len(d["slots"]) == 16 for d in days)
        assert days[0]["slots"][0] == "2026-10-26T09:00:00+03:00"
        assert days[0]["slots"][-1] == "2026-10-26T16:30:00+03:00"
        assert all(datetime.fromisoformat(d["date"]).weekday() < 5 for d in days)

    def test_tomorrow_is_counted_in_addis_ababa(self, client, monkeypatch):
        from app import onboarding

        # 22:30 UTC on Thursday is already Friday 01:30 in Addis Ababa: tomorrow is Saturday.
        monkeypatch.setattr(onboarding, "now", lambda: datetime(2026, 10, 22, 22, 30, tzinfo=timezone.utc))
        headers, _ = apply(client)
        days = client.get("/onboarding/demo-slots", headers=headers).json()["days"]
        assert days[0]["date"] == "2026-10-26"
        assert client.post("/onboarding/demo", headers=headers,
                           json={"demo_at": addis(23, 10)}).status_code == 400  # "today" in Addis

    @pytest.mark.parametrize("demo_at", [
        addis(26, 8, 30), addis(26, 17), addis(26, 9, 15), addis(24, 10),  # before 9, at 5, off the grid, Saturday
        addis(23, 16, 30),  # today
        datetime(2026, 11, 23, 9, 0, tzinfo=ADDIS).isoformat(),  # 31 days ahead
    ])
    def test_only_slots_on_offer_can_be_booked(self, client, demo_at):
        headers, _ = apply(client)
        assert client.post("/onboarding/demo", headers=headers, json={"demo_at": demo_at}).status_code == 400

    def test_a_time_needs_its_offset(self, client):
        headers, _ = apply(client)
        assert client.post("/onboarding/demo", headers=headers,
                           json={"demo_at": "2026-10-26T09:00:00"}).status_code == 422

    def test_the_same_instant_in_utc_is_the_same_slot(self, client):
        headers, _ = ready(client)
        booked = client.post("/onboarding/demo", headers=headers, json={"demo_at": "2026-10-26T06:00:00Z"}).json()
        assert booked["demo"]["demo_at"] == "2026-10-26T09:00:00+03:00"

    def test_a_slot_is_for_one_hospital_and_is_hidden_from_the_others(self, client):
        first, _ = ready(client)
        second, _ = ready(client, admin_email="b@clinic.example", hospital_name="Abebe Clinic")
        assert client.post("/onboarding/demo", headers=first, json={"demo_at": addis(26, 9)}).status_code == 200
        taken = client.post("/onboarding/demo", headers=second, json={"demo_at": addis(26, 9)})
        assert taken.status_code == 409 and "Another hospital" in taken.json()["error"]
        theirs = client.get("/onboarding/demo-slots", headers=second).json()["days"][0]["slots"]
        assert addis(26, 9) not in theirs and len(theirs) == 15
        mine = client.get("/onboarding/demo-slots", headers=first).json()
        assert mine["current"] == addis(26, 9) and addis(26, 9) in mine["days"][0]["slots"]
        # Moving frees the old slot for others.
        client.post("/onboarding/demo", headers=first, json={"demo_at": addis(26, 9, 30)})
        assert client.post("/onboarding/demo", headers=second, json={"demo_at": addis(26, 9)}).status_code == 200

    def test_the_unique_slot_settles_a_race(self, client, monkeypatch):
        """Both requests pass the "is it free" check; the database lets only one in."""
        from app import onboarding

        first, _ = ready(client)
        second, _ = ready(client, admin_email="b@clinic.example", hospital_name="Abebe Clinic")
        client.post("/onboarding/demo", headers=first, json={"demo_at": addis(29, 11)})
        monkeypatch.setattr(onboarding, "taken_slots", lambda *_a, **_k: set())
        lost = client.post("/onboarding/demo", headers=second, json={"demo_at": addis(29, 11)})
        assert lost.status_code == 409 and lost.json()["error"].startswith("Another hospital")
        assert client.get("/onboarding/application", headers=second).json()["demo"] is None

    def test_concurrent_bookings_of_one_slot(self, client):
        accounts = [ready(client, admin_email=f"h{i}@race.example", hospital_name=f"Race Clinic {i}")[0]
                    for i in range(4)]
        barrier = threading.Barrier(len(accounts))
        results = []

        def book(headers):
            barrier.wait()
            results.append(client.post("/onboarding/demo", headers=headers, json={"demo_at": addis(30, 15)}).status_code)

        threads = [threading.Thread(target=book, args=(h,)) for h in accounts]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(results) == [200, 409, 409, 409]
        from app.db import platform_session
        from app.models import DemoBooking
        from sqlalchemy import func, select

        with platform_session() as session:
            assert session.scalar(select(func.count()).select_from(DemoBooking)) == 1

    def test_the_contact_is_texted_through_the_platform(self, client, bus):
        headers, hospital_id = ready(client)
        client.post("/onboarding/demo", headers=headers, json={"demo_at": addis(26, 10)})
        client.post("/onboarding/demo", headers=headers, json={"demo_at": addis(26, 10)})  # same time: no news
        client.post("/onboarding/demo", headers=headers, json={"demo_at": addis(2, 11, 30, month=11)})
        first, changed = published(bus)
        assert set(first) == {"hospital_id", "booking_id", "contact_name", "phone", "demo_at", "hospital_name",
                              "changed"}
        assert first == {"hospital_id": hospital_id, "booking_id": first["booking_id"],
                         "contact_name": "Selam Bekele", "phone": "+251911234567",
                         "demo_at": "2026-10-26T10:00:00+03:00", "hospital_name": "Bethel Teaching Hospital",
                         "changed": False}
        assert re.fullmatch(r"[0-9a-f]{32}", first["booking_id"])
        assert re.fullmatch(r"\+2519\d{8}", first["phone"])
        assert datetime.fromisoformat(first["demo_at"]).utcoffset() == timedelta(hours=3)
        assert changed == {**first, "demo_at": "2026-11-02T11:30:00+03:00", "changed": True}

    def test_no_demo_without_a_mobile_to_text(self, client):
        headers, _ = apply(client, admin_phone=None)
        refused = client.post("/onboarding/demo", headers=headers, json={"demo_at": addis(26, 10)})
        assert refused.status_code == 400 and "mobile" in refused.json()["error"]


class TestEndodReview:
    def test_platform_endpoints_need_the_key(self, client, monkeypatch):
        _headers, hospital_id = apply(client)
        paths = [("GET", "/platform/applications"), ("GET", f"/platform/applications/{hospital_id}"),
                 ("GET", f"/platform/applications/{hospital_id}/documents/owner_id"),
                 ("POST", f"/platform/hospitals/{hospital_id}/reject")]
        for method, path in paths:
            assert client.request(method, path, json={"reason": "x" * 10}).status_code == 401
            assert client.request(method, path, headers={"X-Platform-Key": "wrong"},
                                  json={"reason": "x" * 10}).status_code == 401
        # Staff sessions are not a key.
        headers, _ = apply(client, admin_email="x@y.example", hospital_name="Yet Another")
        assert client.get("/platform/applications", headers=headers).status_code == 401
        monkeypatch.delenv("HOSPITAL_PLATFORM_ADMIN_KEY")
        assert client.get("/platform/applications", headers=KEY).status_code == 404

    def test_list_detail_and_documents(self, client):
        headers, hospital_id = apply(client)
        complete(client, headers)
        client.post("/onboarding/submit", headers=headers)
        _draft_headers, draft_id = apply(client, admin_email="d@draft.example", hospital_name="Draft Clinic",
                                        facility_type="clinic")

        listed = {a["hospital_id"]: a for a in client.get("/platform/applications", headers=KEY).json()}
        assert set(listed) == {draft_id, hospital_id}
        mine, draft = listed[hospital_id], listed[draft_id]
        assert mine["status"] == "submitted" and mine["submitted_at"]
        assert mine["demo_at"] == "2026-10-26T10:00:00+03:00"
        assert mine["contact"]["phone"] == "+251911234567" and mine["contact"]["title"] == "Medical Director"
        assert draft["facility_type"] == "clinic" and draft["demo_at"] is None and draft["status"] == "draft"
        only = client.get("/platform/applications?status=submitted", headers=KEY).json()
        assert [a["hospital_id"] for a in only] == [hospital_id]
        assert client.get("/platform/applications?status=nope", headers=KEY).status_code == 400

        detail = client.get(f"/platform/applications/{hospital_id}", headers=KEY).json()
        assert detail["documents"]["license_number"] == "MOH/AA/1234" and detail["location"] == LOCATION
        document = detail["documents"]["items"][0]
        assert document["download"] == f"/platform/applications/{hospital_id}/documents/moh_license"
        file = client.get(document["download"], headers=KEY)
        assert file.status_code == 200 and file.content == PDF and file.headers["x-sha256"] == document["sha256"]
        assert client.get(f"/platform/applications/{draft_id}/documents/owner_id", headers=KEY).status_code == 404
        assert client.get("/platform/applications/" + "0" * 32, headers=KEY).status_code == 404
        assert client.get(f"/platform/applications/{hospital_id}/documents/..%2f..%2fetc", headers=KEY).status_code == 404

    def test_reject_with_a_reason_then_fix_and_resubmit(self, client):
        headers, hospital_id = apply(client)
        reason = {"reason": "The TIN certificate is unreadable. Upload a clearer scan."}
        # A draft cannot be sent back: there is nothing to review yet.
        assert client.post(f"/platform/hospitals/{hospital_id}/reject", headers=KEY, json=reason).status_code == 409
        complete(client, headers)
        client.post("/onboarding/submit", headers=headers)
        assert client.post(f"/platform/hospitals/{hospital_id}/reject", headers=KEY,
                           json={"reason": "  "}).status_code == 422
        rejected = client.post(f"/platform/hospitals/{hospital_id}/reject", headers=KEY, json=reason).json()
        assert rejected["status"] == "rejected"

        app = client.get("/onboarding/application", headers=headers).json()
        assert app["status"] == "rejected" and app["rejection_reason"] == reason["reason"]
        assert client.get("/hospital", headers=headers).status_code == 403  # still pending
        assert upload(client, headers, "tin_certificate", PNG, "tin.png").status_code == 201
        # Sending it back released the demo slot: they book again before resubmitting.
        assert app["demo"] is None
        assert client.post("/onboarding/submit", headers=headers).json()["error"] == \
            "Finish these steps first: demo booking."
        assert client.post("/onboarding/demo", headers=headers, json={"demo_at": addis(28, 11)}).status_code == 200
        resubmitted = client.post("/onboarding/submit", headers=headers).json()
        assert resubmitted["status"] == "submitted" and resubmitted["rejection_reason"] is None
        assert client.post(f"/platform/hospitals/{hospital_id}/approve", headers=KEY).json()["status"] == "approved"
        assert client.post(f"/platform/hospitals/{hospital_id}/reject", headers=KEY, json=reason).status_code == 409

    def test_cli_lists_and_shows_applications(self, client, capsys, tmp_path):
        from app import cli

        headers, hospital_id = apply(client)
        complete(client, headers)
        client.post("/onboarding/submit", headers=headers)
        assert cli.main(["applications"]) == 0
        out = capsys.readouterr().out
        assert "BTH" in out and "submitted" in out and "Mon 26 Oct 2026 10:00" in out

        assert cli.main(["application", "--code", "bth"]) == 0
        out = capsys.readouterr().out
        assert "Bethel Teaching Hospital (BTH)" in out and "Medical Director" in out
        assert "Mon 26 Oct 2026 10:00 Addis Ababa time" in out and "MOH/AA/1234" in out
        assert str(tmp_path / "files" / hospital_id) in out and "MISSING" not in out
        with pytest.raises(SystemExit):
            cli.main(["application", "--code", "NOPE"])


def test_migration_0005_keeps_existing_hospitals_and_their_patients(tmp_path, monkeypatch):
    """facility_type is added in place: nothing that references hospitals is touched (SQLite)."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app import db as dbmod
    from app.db import get_engine

    monkeypatch.setenv("HOSPITAL_DATABASE_URL", f"sqlite:///{tmp_path / 'before-0005.db'}")
    dbmod.reset_engine()
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "0004")
    with get_engine().begin() as connection:
        connection.execute(text("INSERT INTO hospitals (id, code, name, timezone, created_at) "
                                "VALUES ('h1', 'SPH', 'St. Paul', 'Africa/Addis_Ababa', '2026-01-01 00:00:00')"))
        connection.execute(text(
            "INSERT INTO patients (id, hospital_id, mrn, full_name, sex, dob_estimated, payer, status, "
            "created_at, updated_at) VALUES ('p1', 'h1', 'SPH-000001', 'Almaz', 'female', 0, 'cash', 'opd', "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"))
        connection.execute(text("INSERT INTO staff_users (id, hospital_id, email, full_name, role, password_hash, "
                                "must_change_password, active, failed_logins, created_at) VALUES ('u1', 'h1', "
                                "'a@sph.example', 'Admin', 'admin', 'x', 0, 1, 0, '2026-01-01 00:00:00')"))
    command.upgrade(config, "head")
    with get_engine().connect() as connection:
        assert connection.execute(text("SELECT facility_type, status FROM hospitals")).one() == ("hospital", "approved")
        assert connection.execute(text("SELECT count(*) FROM patients")).scalar() == 1
        assert connection.execute(text("SELECT count(*) FROM staff_users")).scalar() == 1
    with get_engine().begin() as connection:
        connection.execute(text("INSERT INTO demo_bookings (id, hospital_id, slot_start, phone, created_at, updated_at) "
                                "VALUES ('d1', 'h1', '2026-10-26 06:00:00', '+251911000000', '2026-01-01', '2026-01-01')"))
    command.downgrade(config, "0004")
    with get_engine().connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM patients")).scalar() == 1
        assert connection.execute(text("SELECT count(*) FROM hospitals")).scalar() == 1
        columns = [row[1] for row in connection.execute(text("PRAGMA table_info(hospitals)"))]
    dbmod.reset_engine()
    assert "facility_type" not in columns


class TestReviewFixes:
    """Lockout by application, slot hoarding, approval rules, staff of an applicant."""

    def test_a_suspended_applicant_stays_locked_out(self, client, bus):
        headers, hospital_id = ready(client)
        client.post("/onboarding/demo", headers=headers, json={"demo_at": addis(26, 10)})
        assert client.post(f"/platform/hospitals/{hospital_id}/suspend", headers=KEY).status_code == 200
        refused = client.get("/patients", headers=headers)
        assert refused.status_code == 403 and "not approved" in refused.json()["error"]
        assert client.get("/hospital", headers=headers).status_code == 403
        status = client.get("/onboarding/status", headers=headers).json()
        assert status["status"] == "suspended" and status["locked"] is True and status["demo_at"] is None
        assert client.get("/auth/me", headers=headers).json()["hospital"]["locked"] is True
        # Its slot went back to the calendar, and it cannot book another.
        assert client.post("/onboarding/demo", headers=headers, json={"demo_at": addis(27, 10)}).status_code == 409
        other, _ = ready(client, admin_email="o@other.example", hospital_name="Other Clinic")
        assert client.post("/onboarding/demo", headers=other, json={"demo_at": addis(26, 10)}).status_code == 200

    def test_submitted_and_rejected_applications_are_locked_out(self, client):
        headers, hospital_id = apply(client)
        complete(client, headers)
        client.post("/onboarding/submit", headers=headers)
        assert client.get("/patients", headers=headers).status_code == 403
        client.post(f"/platform/hospitals/{hospital_id}/reject", headers=KEY, json={"reason": "Clearer TIN please"})
        assert client.get("/patients", headers=headers).status_code == 403

    def test_hospitals_approved_before_keep_their_access_when_suspended(self, client, admin, hospital):
        assert client.get("/auth/me", headers=admin).json()["hospital"]["locked"] is False
        client.post(f"/platform/hospitals/{hospital}/suspend", headers=KEY)
        assert client.get("/patients", headers=admin).status_code == 200
        # The auto-created application is approved, so Endod can bring it back.
        assert client.post(f"/platform/hospitals/{hospital}/approve", headers=KEY).json()["status"] == "approved"

    def test_a_demo_needs_the_four_documents(self, client):
        headers, _ = apply(client)
        for kind in KINDS[:3]:
            upload(client, headers, kind)
        refused = client.post("/onboarding/demo", headers=headers, json={"demo_at": addis(26, 10)})
        assert refused.status_code == 400 and refused.json()["error"] == "Upload all four documents before booking a demo."
        upload(client, headers, KINDS[3])
        assert client.post("/onboarding/demo", headers=headers, json={"demo_at": addis(26, 10)}).status_code == 200

    def test_one_demo_per_mobile_number_across_hospitals(self, client):
        first, _ = ready(client)
        client.post("/onboarding/demo", headers=first, json={"demo_at": addis(26, 10)})
        # The same person, the number written another way, for another facility.
        second, _ = ready(client, admin_email="again@other.example", hospital_name="Second Clinic",
                          admin_phone="+251 911 234 567")
        refused = client.post("/onboarding/demo", headers=second, json={"demo_at": addis(26, 11)})
        assert refused.status_code == 409 and "already has a demo" in refused.json()["error"]
        # Switching the first application to that number elsewhere is refused too.
        third, _ = ready(client, admin_email="third@other.example", hospital_name="Third Clinic")
        client.post("/onboarding/demo", headers=third, json={"demo_at": addis(26, 12)})
        moved = client.patch("/onboarding/contact", headers=third, json={
            "full_name": "Third Person", "title": "Owner", "phone": "0911 234 567"})
        assert moved.status_code == 409

    def test_an_unsubmitted_booking_is_released_after_a_day(self, client, bus, monkeypatch):
        from app import chores, onboarding

        draft, draft_id = ready(client)
        client.post("/onboarding/demo", headers=draft, json={"demo_at": addis(29, 10)})
        kept, _ = apply(client, admin_email="kept@other.example", hospital_name="Kept Clinic")
        complete(client, kept, demo_at=addis(29, 11))
        client.post("/onboarding/submit", headers=kept)
        before = len(published(bus))

        monkeypatch.setattr(onboarding, "now", lambda: FRIDAY_4PM_ADDIS + timedelta(hours=23))
        other, _ = ready(client, admin_email="o@other.example", hospital_name="Other Clinic")
        taken = client.post("/onboarding/demo", headers=other, json={"demo_at": addis(29, 10)})
        assert taken.status_code == 409  # still held within the day

        monkeypatch.setattr(onboarding, "now", lambda: FRIDAY_4PM_ADDIS + timedelta(hours=25))
        assert chores.run() >= 1  # the worker releases it
        assert client.get("/onboarding/application", headers=draft).json()["demo"] is None
        assert client.post("/onboarding/demo", headers=other, json={"demo_at": addis(29, 10)}).status_code == 200
        # The submitted one keeps its slot; the released one sent nothing more.
        assert client.get("/onboarding/application", headers=kept).json()["demo"]["demo_at"] == addis(29, 11)
        events = published(bus)
        assert len(events) == before + 1 and all(e["hospital_id"] != draft_id for e in events[before:])

    def test_a_lazy_check_also_releases_a_stale_booking(self, client, monkeypatch):
        from app import onboarding

        draft, _ = ready(client)
        client.post("/onboarding/demo", headers=draft, json={"demo_at": addis(30, 10)})
        monkeypatch.setattr(onboarding, "now", lambda: FRIDAY_4PM_ADDIS + timedelta(hours=25))
        other, _ = ready(client, admin_email="o@other.example", hospital_name="Other Clinic")
        days = client.get("/onboarding/demo-slots", headers=other).json()["days"]
        assert addis(30, 10) in next(d for d in days if d["date"] == "2026-10-30")["slots"]

    def test_approval_needs_a_submitted_application(self, client):
        headers, hospital_id = apply(client)
        refused = client.post(f"/platform/hospitals/{hospital_id}/approve", headers=KEY)
        assert refused.status_code == 409
        assert refused.json()["error"] == ("The hospital's application is not submitted yet (status: draft); "
                                           "only a submitted application can be approved.")
        complete(client, headers)
        client.post("/onboarding/submit", headers=headers)
        client.post(f"/platform/hospitals/{hospital_id}/reject", headers=KEY, json={"reason": "Fix the TIN"})
        assert client.post(f"/platform/hospitals/{hospital_id}/approve", headers=KEY).status_code == 409
        assert client.get("/hospital", headers=headers).status_code == 403

    def test_other_staff_of_an_applicant_see_its_status_only(self, client):
        headers, hospital_id = apply(client)
        complete(client, headers)
        client.post("/onboarding/submit", headers=headers)
        make_staff(hospital_id, "nurse@bethel.example", role="nurse")
        make_staff(hospital_id, "second-admin@bethel.example", role="admin")
        for email in ("nurse@bethel.example", "second-admin@bethel.example"):
            other = sign_in(client, email)
            status = client.get("/onboarding/status", headers=other).json()
            assert status == {**status, "name": "Bethel Teaching Hospital", "status": "submitted", "applicant": False,
                              "locked": True, "contact_phone": None, "demo_at": addis(26, 10)}
            refused = client.get("/onboarding/application", headers=other)
            assert refused.status_code == 403 and "contact person" in refused.json()["error"]
            assert client.post("/onboarding/demo", headers=other, json={"demo_at": addis(27, 10)}).status_code == 403
            assert client.get("/patients", headers=other).status_code == 403
        mine = client.get("/onboarding/status", headers=headers).json()
        assert mine["applicant"] is True and mine["contact_phone"] == "+251911234567"

    def test_a_temporary_password_can_be_changed_while_applying(self, client):
        _headers, hospital_id = apply(client)
        make_staff(hospital_id, "temp@bethel.example", role="nurse", must_change=True)
        temp = sign_in(client, "temp@bethel.example")
        assert client.get("/onboarding/status", headers=temp).json()["must_change_password"] is True
        assert client.post("/auth/password", headers=temp, json={
            "current_password": "StaffPass123", "new_password": "Brand-new-pass-1"}).status_code == 200
        status = client.get("/onboarding/status", headers=temp).json()
        assert status["must_change_password"] is False and status["status"] == "draft"

    def test_a_demo_that_has_passed_must_be_booked_again(self, client):
        from sqlalchemy import update

        from app.db import platform_session
        from app.models import DemoBooking

        headers, _ = apply(client)
        complete(client, headers)
        with platform_session() as session:
            session.execute(update(DemoBooking).values(slot_start=FRIDAY_4PM_ADDIS - timedelta(days=1)))
        app = client.get("/onboarding/application", headers=headers).json()
        assert app["missing"]["demo"] == ["demo_at"] and app["next_step"] == "demo"
        assert client.post("/onboarding/submit", headers=headers).status_code == 400
        client.post("/onboarding/demo", headers=headers, json={"demo_at": addis(27, 9)})
        assert client.post("/onboarding/submit", headers=headers).json()["status"] == "submitted"
