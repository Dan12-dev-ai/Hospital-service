"""Helpers for the patient-history tests: the event bus, staff, patients, files."""

import json
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import fakeredis
import pytest

from conftest import make_staff, sign_in

PLATFORM_KEY = "platform-test-key"
#: Every hospital in these tests keeps Addis Ababa time (dates depend on it).
ZONE = ZoneInfo("Africa/Addis_Ababa")

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 24
EXE = b"MZ\x90\x00" + b"\x00" * 32


@pytest.fixture(autouse=True)
def platform_key(monkeypatch):
    monkeypatch.setenv("HOSPITAL_PLATFORM_ADMIN_KEY", PLATFORM_KEY)


@pytest.fixture
def bus():
    return fakeredis.FakeRedis(decode_responses=True)


def today():
    return datetime.now(ZONE).date()


def events(bus, event_type=None):
    """What this service published, after the outbox is relayed."""
    from app import eventbus

    eventbus.publish_pending(bus)
    out = [(f["type"], json.loads(f["payload"])) for _id, f in bus.xrange("endod:hospital")]
    return [p for t, p in out if t == event_type] if event_type else out


def send(bus, event_type, payload, event_id=None):
    """The patient platform publishing an event."""
    bus.xadd("endod:patient", {"id": event_id or uuid.uuid4().hex, "type": event_type, "source": "platform",
                               "occurred_at": datetime.now(timezone.utc).isoformat(),
                               "payload": json.dumps(payload)})


def consume(bus):
    from app import eventbus, worker

    return eventbus.consume_once(bus, worker.handlers(), block_ms=10)


def dead_letters(bus):
    return bus.xrange("endod:dead-letter")


def staff(client, hospital, role, name=None):
    email = f"{name or role}@sph.example"
    user_id = make_staff(hospital, email, role=role)
    headers = sign_in(client, email)
    headers["X-Staff-Id"] = user_id  # ignored by the API; handy in tests
    return headers


def register(client, headers, name="Almaz Tefera", phone="0911 234 567", **extra):
    resp = client.post("/patients", headers=headers, json={"full_name": name, "sex": "female", "age_years": 40,
                                                           "phone": phone, "confirm_duplicate": True, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


def link_directly(patient_id, dedan_id):
    """As if Endod had confirmed the link (the patient.linked handler's effect)."""
    from app.db import session_scope
    from app.models import Patient

    with session_scope() as session:
        session.get(Patient, patient_id).dedan_id = dedan_id


def upload(client, headers, patient_id, data=PDF, filename="report.pdf", extra_headers=None):
    from urllib.parse import quote

    return client.post(f"/patients/{patient_id}/uploads", headers={
        **headers, "Content-Type": "application/octet-stream", "X-Filename": quote(filename),
        **(extra_headers or {})}, content=data)
