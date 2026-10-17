import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PASSWORD = "StaffPass123"


@pytest.fixture
def db(tmp_path, monkeypatch):
    from app import db as dbmod

    monkeypatch.setenv("HOSPITAL_DATABASE_URL", f"sqlite:///{tmp_path / 'hospital.db'}")
    monkeypatch.setenv("HOSPITAL_ENVIRONMENT", "development")
    dbmod.reset_engine()
    dbmod.create_all()
    yield
    dbmod.reset_engine()


@pytest.fixture
def client(db):
    from app.main import create_app

    return TestClient(create_app())


def make_hospital(code="SPH", name="St. Paul's Millennium Medical Center"):
    from app.db import session_scope
    from app.models import Hospital

    with session_scope() as session:
        hospital = Hospital(code=code, name=name)
        session.add(hospital)
        session.flush()
        return hospital.id


def make_staff(hospital_id, email, role="admin", password=PASSWORD, must_change=False, active=True):
    from app.db import session_scope
    from app.models import StaffUser
    from app.security import hash_password

    with session_scope() as session:
        user = StaffUser(hospital_id=hospital_id, email=email, full_name=email.split("@")[0].title(),
                         role=role, password_hash=hash_password(password), must_change_password=must_change,
                         active=active)
        session.add(user)
        session.flush()
        return user.id


def sign_in(client, email, password=PASSWORD):
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def hospital(db):
    return make_hospital()


@pytest.fixture
def admin(client, hospital):
    make_staff(hospital, "admin@sph.example", role="admin")
    return sign_in(client, "admin@sph.example")
