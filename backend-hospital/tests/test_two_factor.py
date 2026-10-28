"""Two-step verification (app/twofactor.py): setting up the authenticator,
signing in with a code or a recovery code, replays, throttles, approval,
resets and re-authentication."""

import pyotp
import pytest
from sqlalchemy import select, text

from conftest import PASSWORD, bearer, make_hospital, make_staff, sign_in, totp_code, totp_secret

from app import totp, twofactor
from app.db import get_engine, platform_session
from app.models import AuditEvent, OnboardingApplication, StaffSession, StaffUser


def login(client, email, password=PASSWORD, headers=None):
    resp = client.post("/auth/login", json={"email": email, "password": password}, headers=headers or {})
    assert resp.status_code == 200, resp.text
    return resp.json()


def enrol(client, email):
    """Signs in for the first time and sets up the authenticator; returns (full session headers, recovery codes)."""
    pending = login(client, email)
    assert pending["stage"] == "enroll"
    started = client.post("/auth/enroll/start", headers=bearer(pending)).json()
    done = client.post("/auth/enroll/confirm", headers=bearer(pending), json={"code": totp_code(started["secret"])})
    assert done.status_code == 200, done.text
    return bearer(done.json()), done.json()["recovery_codes"]


def actions():
    with platform_session() as session:
        return [a.action for a in session.scalars(select(AuditEvent).order_by(AuditEvent.at))]


@pytest.fixture
def nurse(hospital):
    make_staff(hospital, "nurse@sph.example", role="nurse")
    return "nurse@sph.example"


class TestEnrolment:
    def test_staff_of_an_approved_hospital_set_up_an_authenticator_first(self, client, nurse):
        pending = login(client, nurse)
        assert pending["stage"] == "enroll" and pending["expires_in"] == 600
        refused = client.get("/patients", headers=bearer(pending))
        assert refused.status_code == 403 and refused.json()["error"] == "Finish signing in first."
        assert client.get("/auth/me", headers=bearer(pending)).json()["stage"] == "enroll"
        started = client.post("/auth/enroll/start", headers=bearer(pending)).json()
        assert started["otpauth_uri"].startswith("otpauth://totp/") and "issuer=Endod%20Hospital" in started["otpauth_uri"]
        # Asking again shows the same secret until it is confirmed.
        assert client.post("/auth/enroll/start", headers=bearer(pending)).json()["secret"] == started["secret"]
        wrong = client.post("/auth/enroll/confirm", headers=bearer(pending), json={"code": "123456"})
        assert wrong.status_code == 400
        done = client.post("/auth/enroll/confirm", headers=bearer(pending),
                           json={"code": totp_code(started["secret"])}).json()
        assert done["stage"] == "full" and len(done["recovery_codes"]) == 10 and len(set(done["recovery_codes"])) == 10
        assert client.get("/patients", headers=bearer(done)).status_code == 200
        assert client.get("/auth/me", headers=bearer(pending)).status_code == 401  # the half-way session ended
        me = client.get("/auth/me", headers=bearer(done)).json()
        assert me["two_factor_enrolled"] is True and me["recovery_codes_left"] == 10
        assert "staff_2fa_enrolled" in actions()

    def test_secrets_are_encrypted_and_recovery_codes_hashed(self, client, nurse):
        _headers, codes = enrol(client, nurse)
        with get_engine().connect() as connection:
            stored = connection.execute(text("SELECT totp_secret, totp_pending_secret FROM staff_users")).one()
            hashes = connection.execute(text("SELECT code_hash FROM staff_recovery_codes")).scalars().all()
        assert stored[0].startswith("enc:v1:") and stored[1] is None
        assert totp_secret(nurse) not in stored[0]
        assert len(hashes) == 10 and not set(codes) & set(hashes)
        assert all(c.replace("-", "") not in h for c in codes for h in hashes)

    def test_a_hospital_still_applying_signs_in_with_the_password_only(self, client):
        applying = make_hospital(code="NEW", name="New Clinic")
        with platform_session() as session:
            session.add(OnboardingApplication(hospital_id=applying, status="submitted"))
        make_staff(applying, "applicant@new.example")
        assert login(client, "applicant@new.example")["stage"] == "full"

    def test_a_temporary_password_is_changed_before_the_authenticator(self, client, hospital):
        make_staff(hospital, "temp@sph.example", must_change=True)
        pending = login(client, "temp@sph.example")
        assert pending["stage"] == "enroll"
        refused = client.post("/auth/enroll/start", headers=bearer(pending))
        assert refused.status_code == 403 and "temporary password" in refused.json()["error"]
        assert client.get("/patients", headers=bearer(pending)).json()["error"] == \
            "Change your temporary password to continue."
        assert client.post("/auth/password", headers=bearer(pending),
                           json={"current_password": PASSWORD, "new_password": "BrandNewPass1"}).status_code == 200
        assert client.post("/auth/enroll/start", headers=bearer(pending)).status_code == 200

    def test_approval_ends_every_session_so_the_next_sign_in_sets_it_up(self, client):
        applying = make_hospital(code="APP", name="Applying Hospital")
        with platform_session() as session:
            session.add(OnboardingApplication(hospital_id=applying, status="submitted"))
        make_staff(applying, "admin@app.example")
        before = bearer(login(client, "admin@app.example"))
        assert client.get("/auth/me", headers=before).status_code == 200
        from app.api.onboarding import set_status
        set_status(applying, "approved")
        assert client.get("/auth/me", headers=before).status_code == 401
        assert login(client, "admin@app.example")["stage"] == "enroll"


class TestSignIn:
    def test_password_then_code(self, client, nurse):
        enrol(client, nurse)
        pending = login(client, nurse)
        assert pending["stage"] == "totp"
        assert client.get("/patients", headers=bearer(pending)).status_code == 403
        assert client.post("/auth/password", headers=bearer(pending), json={
            "current_password": PASSWORD, "new_password": "BrandNewPass1"}).status_code == 403
        done = client.post("/auth/totp", headers=bearer(pending), json={"code": totp_code(totp_secret(nurse))})
        assert done.status_code == 200 and done.json()["stage"] == "full"
        assert client.get("/patients", headers=bearer(done.json())).status_code == 200

    def test_a_code_works_once(self, client, nurse):
        enrol(client, nurse)
        code = totp_code(totp_secret(nurse))
        first = login(client, nurse)
        assert client.post("/auth/totp", headers=bearer(first), json={"code": code}).status_code == 200
        second = login(client, nurse)
        replay = client.post("/auth/totp", headers=bearer(second), json={"code": code})
        assert replay.status_code == 400
        # ... and so does any older one.
        secret = totp_secret(nurse)
        older = pyotp.TOTP(secret).at(totp._clock() - totp.INTERVAL)
        assert client.post("/auth/totp", headers=bearer(second), json={"code": older}).status_code == 400

    def test_recovery_codes_work_once(self, client, nurse):
        _headers, codes = enrol(client, nurse)
        pending = login(client, nurse)
        done = client.post("/auth/totp", headers=bearer(pending), json={"recovery_code": codes[0].upper()})
        assert done.status_code == 200 and done.json()["recovery_codes_left"] == 9
        again = login(client, nurse)
        assert client.post("/auth/totp", headers=bearer(again), json={"recovery_code": codes[0]}).status_code == 400
        assert client.post("/auth/totp", headers=bearer(again), json={"recovery_code": codes[1]}).status_code == 200

    def test_a_pending_session_reaches_nothing_else(self, client, nurse):
        enrol(client, nurse)
        pending = bearer(login(client, nurse))
        for method, path in (("GET", "/hospital"), ("GET", "/onboarding/application"), ("POST", "/auth/reauth"),
                             ("POST", "/auth/enroll/start")):
            assert client.request(method, path, headers=pending, json={"code": "123456"}).status_code in (403, 409)


class TestThrottles:
    def test_an_account_pauses_after_wrong_codes_and_nobody_is_signed_out(self, client, nurse, monkeypatch):
        monkeypatch.setenv("HOSPITAL_TRUSTED_PROXY_HOPS", "1")
        full, _codes = enrol(client, nurse)
        pending = login(client, nurse)
        for n in range(twofactor.CODE_BACKOFF_AFTER):  # from different addresses: the account counts them all
            wrong = client.post("/auth/totp", headers={**bearer(pending), "X-Forwarded-For": f"198.51.100.{n}"},
                                json={"code": "000000"})
            assert wrong.status_code == 400
        paused = client.post("/auth/totp", headers={**bearer(pending), "X-Forwarded-For": "203.0.113.9"},
                             json={"code": totp_code(totp_secret(nurse))})
        assert paused.status_code == 429 and "Wait" in paused.json()["error"]
        assert client.get("/patients", headers=full).status_code == 200  # no session ended
        assert client.get("/auth/me", headers=bearer(pending)).status_code == 200
        with platform_session() as session:
            user = session.scalar(select(StaffUser).where(StaffUser.email == nurse))
            assert user.code_failures == 5 and user.code_backoff_until is not None

    def test_per_address_and_per_account_address(self, client, hospital, nurse, monkeypatch):
        monkeypatch.setattr(twofactor, "CODE_FAILURES_PER_PAIR", twofactor.Failures(2, 900))
        monkeypatch.setattr(twofactor, "CODE_FAILURES_PER_ADDRESS", twofactor.Failures(3, 900))
        enrol(client, nurse)
        make_staff(hospital, "doc@sph.example", role="doctor")
        enrol(client, "doc@sph.example")
        pending = login(client, nurse)
        for _ in range(2):
            client.post("/auth/totp", headers=bearer(pending), json={"code": "000000"})
        pair = client.post("/auth/totp", headers=bearer(pending), json={"code": totp_code(totp_secret(nurse))})
        assert pair.status_code == 429
        other = login(client, "doc@sph.example")
        client.post("/auth/totp", headers=bearer(other), json={"code": "000000"})  # the address's 3rd
        address = client.post("/auth/totp", headers=bearer(other),
                              json={"code": totp_code(totp_secret("doc@sph.example"))})
        assert address.status_code == 429 and "address" in address.json()["error"]


class TestResetAndReauth:
    def test_an_admin_resets_someones_authenticator_with_a_fresh_code(self, client, hospital, nurse):
        nurse_headers, _ = enrol(client, nurse)
        make_staff(hospital, "boss@sph.example", role="admin")
        boss = sign_in(client, "boss@sph.example")
        user_id = client.get("/auth/me", headers=nurse_headers).json()["id"]
        stale = client.post(f"/staff/{user_id}/reset-2fa", headers=boss)
        assert stale.status_code == 403 and stale.json()["error"] == twofactor.REAUTH_REQUIRED
        fresh = client.post("/auth/reauth", headers=boss, json={"code": totp_code(totp_secret("boss@sph.example"))})
        assert fresh.status_code == 200 and "fresh_until" in fresh.json()
        boss_id = client.get("/auth/me", headers=boss).json()["id"]
        assert client.post(f"/staff/{boss_id}/reset-2fa", headers=boss).status_code == 400  # not one's own
        assert client.post(f"/staff/{user_id}/reset-2fa", headers=boss).status_code == 200
        assert client.get("/auth/me", headers=nurse_headers).status_code == 401
        assert login(client, nurse)["stage"] == "enroll"
        with platform_session() as session:
            assert session.scalar(select(AuditEvent).where(AuditEvent.action == "staff_2fa_reset")).target_id == user_id

    def test_a_recovery_code_does_not_reauthenticate(self, client, nurse):
        headers, codes = enrol(client, nurse)
        assert client.post("/auth/reauth", headers=headers, json={"code": codes[0][:12]}).status_code in (400, 422)

    def test_the_cli_resets_anyone(self, client, nurse, capsys):
        from app import cli

        headers, _ = enrol(client, nurse)
        assert cli.main(["reset-2fa", "--email", nurse.upper()]) == 0
        assert "reset" in capsys.readouterr().out
        assert client.get("/auth/me", headers=headers).status_code == 401
        assert login(client, nurse)["stage"] == "enroll"
        with platform_session() as session:
            assert session.scalar(select(StaffSession).where(StaffSession.revoked_at.is_(None),
                                                             StaffSession.stage == "full")) is None
