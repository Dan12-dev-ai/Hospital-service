import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PASSWORD = "StaffPass123"


#: The role the app connects as in the PostgreSQL run (not the owner): every
#: test then goes through the row-level security policies (app/rls.py).
APP_ROLE = "hospital_app"
APP_PASSWORD = "test-only-app-password"


def app_url(owner_url: str) -> str:
    """The test database's URL for the app role."""
    from sqlalchemy.engine import make_url

    return make_url(owner_url).set(username=APP_ROLE, password=APP_PASSWORD).render_as_string(hide_password=False)


def postgres_url():
    return os.environ.get("HOSPITAL_TEST_DATABASE_URL")


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh database per test: SQLite by default, or the PostgreSQL
    database in HOSPITAL_TEST_DATABASE_URL (emptied before every test).

    On PostgreSQL the tables are created as the owner (that URL), the policies
    and the app role are set up as the migrations do, and the app then
    connects as the app role."""
    from app import crypto
    from app import db as dbmod
    from app import models  # noqa: F401  (registers the tables)
    from app import rls

    owner = postgres_url()
    url = owner or f"sqlite:///{tmp_path / 'hospital.db'}"
    monkeypatch.setenv("HOSPITAL_DATABASE_URL", url)
    monkeypatch.setenv("HOSPITAL_ENVIRONMENT", "development")
    monkeypatch.setenv("HOSPITAL_FILES_DIR", str(tmp_path / "files"))
    # A fresh master key per test (as production's: 32 random bytes in a file).
    key_file = tmp_path / "master.key"
    key_file.write_bytes(os.urandom(32))
    monkeypatch.setenv("HOSPITAL_MASTER_KEY_FILE", str(key_file))
    crypto.clear_cache()
    dbmod.reset_engine()
    dbmod.Base.metadata.drop_all(dbmod.get_engine())
    dbmod.create_all()
    if owner:
        with dbmod.get_engine().begin() as connection:
            rls.install(connection)
            rls.set_up_app_role(connection, APP_ROLE, APP_PASSWORD, dbmod.Base.metadata.tables)
        dbmod.reset_engine()
        monkeypatch.setenv("HOSPITAL_DATABASE_URL", app_url(owner))
    yield
    dbmod.reset_engine()


@pytest.fixture
def client(db):
    from app.main import create_app

    return TestClient(create_app())


def make_hospital(code="SPH", name="St. Paul's Millennium Medical Center"):
    from app.db import platform_session
    from app.models import Hospital

    with platform_session() as session:
        hospital = Hospital(code=code, name=name)
        session.add(hospital)
        session.flush()
        return hospital.id


def make_staff(hospital_id, email, role="admin", password=PASSWORD, must_change=False, active=True):
    from app.db import platform_session
    from app.models import StaffUser
    from app.security import hash_password

    with platform_session() as session:
        user = StaffUser(hospital_id=hospital_id, email=email, full_name=email.split("@")[0].title(),
                         role=role, password_hash=hash_password(password), must_change_password=must_change,
                         active=active)
        session.add(user)
        session.flush()
        return user.id


#: The test clock of TOTP codes, ahead of the real one by this many seconds:
#: each code a test makes moves it on, so no code is a replay of an earlier one.
TOTP_CLOCK = {"offset": 0.0}


@pytest.fixture(autouse=True)
def totp_clock(monkeypatch):
    import time

    from app import totp, twofactor

    TOTP_CLOCK["offset"] = 0.0
    monkeypatch.setattr(totp, "_clock", lambda: time.time() + TOTP_CLOCK["offset"])
    twofactor.reset_throttles()
    yield
    twofactor.reset_throttles()


def totp_secret(email):
    """The account's authenticator secret, as its phone holds it."""
    from sqlalchemy import select

    from app.db import platform_session
    from app.models import StaffUser

    with platform_session() as session:
        user = session.scalar(select(StaffUser).where(StaffUser.email == email.lower()))
        return user.totp_secret


def totp_code(secret):
    """A code from the authenticator, at a step no earlier code used."""
    import pyotp

    from app import totp

    TOTP_CLOCK["offset"] += 2 * totp.INTERVAL
    return pyotp.TOTP(secret).at(totp._clock())


def bearer(body):
    return {"Authorization": f"Bearer {body['access_token']}"}


def finish_sign_in(client, email, body):
    """The steps after the password: the code, or setting up the authenticator."""
    if body.get("stage") == "enroll" and not body["staff"]["must_change_password"]:
        started = client.post("/auth/enroll/start", headers=bearer(body))
        assert started.status_code == 200, started.text
        done = client.post("/auth/enroll/confirm", headers=bearer(body),
                           json={"code": totp_code(started.json()["secret"])})
        assert done.status_code == 200, done.text
        return done.json()
    if body.get("stage") == "totp":
        done = client.post("/auth/totp", headers=bearer(body), json={"code": totp_code(totp_secret(email))})
        assert done.status_code == 200, done.text
        return done.json()
    return body


def reauth(client, headers, email):
    resp = client.post("/auth/reauth", headers=headers, json={"code": totp_code(totp_secret(email))})
    assert resp.status_code == 200, resp.text


def sign_in(client, email, password=PASSWORD, fresh=False):
    """Signed in: the password, then the code (setting up the authenticator the
    first time, for staff of an approved hospital). ``fresh``: also a fresh code
    (re-authentication) for sensitive actions."""
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    headers = bearer(finish_sign_in(client, email, resp.json()))
    if fresh:
        reauth(client, headers, email)
    return headers


@pytest.fixture
def hospital(db):
    return make_hospital()


@pytest.fixture
def admin(client, hospital):
    make_staff(hospital, "admin@sph.example", role="admin")
    return sign_in(client, "admin@sph.example")
