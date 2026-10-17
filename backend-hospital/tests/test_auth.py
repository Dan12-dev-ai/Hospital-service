from conftest import PASSWORD, make_hospital, make_staff, sign_in


class TestSignIn:
    def test_sign_in_and_me(self, client, hospital):
        make_staff(hospital, "nurse@sph.example", role="nurse")
        resp = client.post("/auth/login", json={"email": "NURSE@sph.example", "password": PASSWORD})
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "Bearer" and body["staff"]["role"] == "nurse"
        assert body["staff"]["hospital"]["code"] == "SPH"
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}).json()
        assert me["email"] == "nurse@sph.example"

    def test_wrong_password_and_unknown_email_look_the_same(self, client, hospital):
        make_staff(hospital, "a@sph.example")
        wrong = client.post("/auth/login", json={"email": "a@sph.example", "password": "Nope12345678"})
        unknown = client.post("/auth/login", json={"email": "who@sph.example", "password": "Nope12345678"})
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json()["error"] == unknown.json()["error"]

    def test_lockout_after_repeated_failures(self, client, hospital, monkeypatch):
        monkeypatch.setenv("HOSPITAL_LOGIN_LOCKOUT_ATTEMPTS", "3")
        make_staff(hospital, "a@sph.example")
        for _ in range(3):
            client.post("/auth/login", json={"email": "a@sph.example", "password": "Wrong1234567"})
        # Locked: even the right password fails, with the same answer as a wrong one.
        resp = client.post("/auth/login", json={"email": "a@sph.example", "password": PASSWORD})
        assert resp.status_code == 401 and resp.json()["error"] == "Incorrect email or password."

    def test_old_failures_are_forgotten(self, client, hospital, monkeypatch):
        from datetime import timedelta

        from sqlalchemy import update

        from app.db import session_scope, utcnow
        from app.models import StaffUser

        monkeypatch.setenv("HOSPITAL_LOGIN_LOCKOUT_ATTEMPTS", "3")
        make_staff(hospital, "a@sph.example")
        for _ in range(2):
            client.post("/auth/login", json={"email": "a@sph.example", "password": "Wrong1234567"})
        with session_scope() as session:  # the two failures happened long ago
            session.execute(update(StaffUser).values(last_failed_at=utcnow() - timedelta(days=1)))
        client.post("/auth/login", json={"email": "a@sph.example", "password": "Wrong1234567"})
        sign_in(client, "a@sph.example")

    def test_deactivated_account_cannot_sign_in(self, client, hospital):
        make_staff(hospital, "gone@sph.example", active=False)
        resp = client.post("/auth/login", json={"email": "gone@sph.example", "password": PASSWORD})
        assert resp.status_code == 403

    def test_requests_need_a_valid_token(self, client, hospital):
        assert client.get("/auth/me").status_code == 401
        assert client.get("/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert client.get("/hospital", headers={"Authorization": "Basic abc"}).status_code == 401


class TestSessions:
    def test_logout_ends_the_session(self, client, admin):
        assert client.post("/auth/logout", headers=admin).status_code == 200
        assert client.get("/auth/me", headers=admin).status_code == 401

    def test_expired_session_is_refused(self, client, hospital, monkeypatch):
        make_staff(hospital, "a@sph.example")
        monkeypatch.setenv("HOSPITAL_SESSION_TTL_SECONDS", "-1")
        headers = sign_in(client, "a@sph.example")
        assert client.get("/auth/me", headers=headers).status_code == 401

    def test_only_the_token_hash_is_stored(self, client, hospital):
        from sqlalchemy import select

        from app.db import session_scope
        from app.models import StaffSession

        make_staff(hospital, "a@sph.example")
        token = sign_in(client, "a@sph.example")["Authorization"].split()[1]
        with session_scope() as session:
            stored = session.scalars(select(StaffSession.token_hash)).all()
        assert token not in stored and len(stored) == 1


class TestTemporaryPassword:
    def test_must_change_before_using_the_portal(self, client, hospital):
        make_staff(hospital, "new@sph.example", must_change=True)
        headers = sign_in(client, "new@sph.example")
        assert client.get("/auth/me", headers=headers).json()["must_change_password"] is True
        assert client.get("/hospital", headers=headers).status_code == 403

        resp = client.post("/auth/password", headers=headers,
                           json={"current_password": PASSWORD, "new_password": "BrandNewPass1"})
        assert resp.status_code == 200
        assert client.get("/hospital", headers=headers).status_code == 200

    def test_password_rules(self, client, admin):
        for weak in ("short", "alllowercase123", "ALLUPPERCASE123"):
            resp = client.post("/auth/password", headers=admin,
                               json={"current_password": PASSWORD, "new_password": weak})
            assert resp.status_code == 400

    def test_wrong_current_password_is_400_and_counted(self, client, hospital, monkeypatch):
        monkeypatch.setenv("HOSPITAL_LOGIN_LOCKOUT_ATTEMPTS", "3")
        make_staff(hospital, "a@sph.example")
        headers = sign_in(client, "a@sph.example")
        for _ in range(2):
            resp = client.post("/auth/password", headers=headers,
                               json={"current_password": "Guess1234567", "new_password": "AnotherPass12"})
            assert resp.status_code == 400
        assert client.get("/auth/me", headers=headers).status_code == 200
        client.post("/auth/password", headers=headers,
                    json={"current_password": "Guess1234567", "new_password": "AnotherPass12"})
        # The limit is reached: the session ends and the account is locked.
        assert client.get("/auth/me", headers=headers).status_code == 401
        assert client.post("/auth/login", json={"email": "a@sph.example", "password": PASSWORD}).status_code == 401

    def test_change_ends_other_sessions_but_not_this_one(self, client, hospital):
        make_staff(hospital, "a@sph.example")
        first = sign_in(client, "a@sph.example")
        second = sign_in(client, "a@sph.example")
        client.post("/auth/password", headers=first,
                    json={"current_password": PASSWORD, "new_password": "AnotherPass12"})
        assert client.get("/auth/me", headers=first).status_code == 200
        assert client.get("/auth/me", headers=second).status_code == 401


def test_hospitals_are_isolated(client, hospital):
    other = make_hospital(code="BLH", name="Black Lion")
    make_staff(hospital, "admin@sph.example")
    make_staff(other, "admin@blh.example")
    headers = sign_in(client, "admin@blh.example")
    assert client.get("/hospital", headers=headers).json()["code"] == "BLH"
    names = [s["email"] for s in client.get("/staff", headers=headers).json()]
    assert names == ["admin@blh.example"]
