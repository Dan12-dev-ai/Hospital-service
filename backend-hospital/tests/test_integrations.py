"""The integration API for hospitals' own systems (docs/integrations.md):
connections in the portal, tokens, scopes, FHIR writes, bookings, webhooks,
the request log and the audit trail."""

import base64
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from sqlalchemy import func, select

from conftest import PASSWORD, make_hospital, make_staff, sign_in

from app import bookings
from app.db import platform_session
from app.integrations import clients, jose, ratelimit, signing, tokens, webhooks
from app.models import (
    ApplicationStatus, AuditEvent, Booking, ClinicalRecord, DeliveryStatus, Hospital, IntegrationClient,
    IntegrationRequest, IntegrationResource, OnboardingApplication, OutboxEvent, Patient,
    RecordFile, WebhookDelivery,
)

API = "/integrations/v1"
ENDOD = "https://endod-health.com/id"
MRN_SYSTEM = "https://endod-health.com/hospital/sph/mrn"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
MARK = "MARKER-7731-CLINICAL"
ALL_RECORDS = ["records.labs.write", "records.prescriptions.write", "records.diagnoses.write",
               "records.visits.write", "records.documents.write", "records.imaging.write"]


@pytest.fixture(autouse=True)
def fresh_limits():
    ratelimit.reset_all()
    yield
    ratelimit.reset_all()


def make_patient(hospital_id, mrn="SPH-000001", dedan_id=None, name="Almaz Tefera"):
    with platform_session() as session:
        patient = Patient(hospital_id=hospital_id, mrn=mrn, full_name=name, sex="female", dedan_id=dedan_id)
        session.add(patient)
        session.flush()
        return patient.id


def connect(client, admin, scopes=None, mode="live", webhook_url=None, name="Lab system", password=PASSWORD):
    body = {"name": name, "scopes": ALL_RECORDS if scopes is None else scopes, "mode": mode, "password": password}
    if webhook_url:
        body["webhook_url"] = webhook_url
    return client.post("/connections", headers=admin, json=body)


def connected(client, admin, **kwargs):
    resp = connect(client, admin, **kwargs)
    assert resp.status_code == 201, resp.text
    return resp.json()


def basic(client_id, secret):
    return {"Authorization": "Basic " + base64.b64encode(f"{client_id}:{secret}".encode()).decode()}


def token_request(client, data=None, headers=None):
    return client.post(f"{API}/oauth/token", data={"grant_type": "client_credentials", **(data or {})},
                       headers=headers or {})


def get_token(client, conn, scope=None):
    data = {"scope": scope} if scope else {}
    resp = token_request(client, data, basic(conn["connection"]["client_id"], conn["client_secret"]))
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def post_bundle(client, auth, entries, kind="transaction", headers=None):
    bundle = {"resourceType": "Bundle", "type": kind, "entry": entries}
    return client.post(f"{API}/fhir", headers={**auth, "Content-Type": "application/fhir+json", **(headers or {})},
                       content=json.dumps(bundle))


def subject(mrn="SPH-000001", system=MRN_SYSTEM):
    return {"identifier": {"system": system, "value": mrn}}


def observation(test="Hemoglobin", value=13.2, rid=None, version=None, mrn="SPH-000001", system=MRN_SYSTEM):
    r = {"resourceType": "Observation", "status": "final",
         "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                   "code": "laboratory"}]}],
         "code": {"text": test}, "subject": subject(mrn, system), "effectiveDateTime": "2026-10-01T09:00:00+03:00",
         "valueQuantity": {"value": value, "unit": "g/dL"}}
    if rid:
        r["id"] = rid
    if version:
        r["meta"] = {"versionId": version}
    return r


def entry(resource, method="POST"):
    out = {"resource": resource}
    if method == "PUT":
        out["request"] = {"method": "PUT", "url": f"{resource['resourceType']}/{resource['id']}"}
    elif method:
        out["request"] = {"method": "POST", "url": resource["resourceType"]}
    return out


def records_of(patient_id):
    with platform_session() as session:
        return list(session.scalars(select(ClinicalRecord).where(ClinicalRecord.patient_id == patient_id)
                                    .order_by(ClinicalRecord.created_at)))


def count(model):
    with platform_session() as session:
        return session.scalar(select(func.count()).select_from(model))


def set_status(hospital_id, status=None, application=None):
    with platform_session() as session:
        if status:
            session.get(Hospital, hospital_id).status = status
        if application:
            row = session.get(OnboardingApplication, hospital_id)
            if row is None:
                session.add(OnboardingApplication(hospital_id=hospital_id, status=application))
            else:
                row.status = application


@pytest.fixture
def patient(hospital):
    return make_patient(hospital)


@pytest.fixture
def conn(client, admin):
    return connected(client, admin)


@pytest.fixture
def auth(client, conn, patient):
    return get_token(client, conn)


# --- the portal: connections -----------------------------------------------------------------------

class TestConnections:
    def test_connect_shows_the_secret_once_and_stores_only_its_hash(self, client, admin, hospital):
        body = connected(client, admin, scopes=["records.labs.write", "bookings.read"])
        secret, connection = body["client_secret"], body["connection"]
        assert len(secret) >= 40 and connection["client_id"].startswith("endod_live_")
        assert connection["abilities"] == ["Send lab results", "See bookings"]
        assert body["token_url"].endswith("/oauth/token") and body["mrn_system"] == MRN_SYSTEM
        listed = client.get("/connections", headers=admin).json()
        assert [c["id"] for c in listed["items"]] == [connection["id"]]
        assert secret not in json.dumps(listed)
        assert secret not in json.dumps(client.get(f"/connections/{connection['id']}", headers=admin).json())
        with platform_session() as session:
            row = session.get(IntegrationClient, connection["id"])
            assert row.secret_hash.startswith("$argon2id$") and secret not in row.secret_hash

    def test_connecting_needs_the_password_again(self, client, admin):
        resp = connect(client, admin, password="wrong-password")
        assert resp.status_code == 400 and "password" in resp.json()["error"]
        assert connect(client, admin, password="").status_code == 400
        assert count(IntegrationClient) == 0

    def test_only_admins_of_approved_hospitals(self, client, admin, hospital):
        make_staff(hospital, "nurse@sph.example", role="nurse")
        nurse = sign_in(client, "nurse@sph.example")
        assert client.get("/connections", headers=nurse).status_code == 403
        assert connect(client, nurse).status_code == 403
        set_status(hospital, status="suspended")
        resp = client.get("/connections", headers=admin)
        assert resp.status_code == 403 and "approved" in resp.json()["error"]
        set_status(hospital, status="approved", application=ApplicationStatus.SUBMITTED)
        assert client.get("/connections", headers=admin).status_code == 403  # still applying
        set_status(hospital, application=ApplicationStatus.APPROVED)
        assert client.get("/connections", headers=admin).status_code == 200

    def test_invalid_connections(self, client, admin):
        assert connect(client, admin, scopes=["records.everything"]).status_code == 400
        assert connect(client, admin, scopes=[]).status_code == 422
        assert connect(client, admin, mode="sandbox").status_code == 400
        assert connect(client, admin, scopes=["webhooks"]).status_code == 400  # needs an address
        assert connect(client, admin, scopes=["webhooks"], webhook_url="http://hooks.example.com/x").status_code == 400

    def test_connect_rotate_and_disconnect_are_audited_without_secrets(self, client, admin, hospital):
        body = connected(client, admin)
        cid = body["connection"]["id"]
        rotated = client.post(f"/connections/{cid}/rotate-secret", headers=admin, json={"password": PASSWORD})
        assert rotated.status_code == 200 and rotated.json()["client_secret"] != body["client_secret"]
        assert client.post(f"/connections/{cid}/disconnect", headers=admin,
                           json={"password": "nope"}).status_code == 400
        assert client.post(f"/connections/{cid}/disconnect", headers=admin,
                           json={"password": PASSWORD}).status_code == 200
        assert client.get("/connections", headers=admin).json()["items"] == []
        assert client.post(f"/connections/{cid}/rotate-secret", headers=admin,
                           json={"password": PASSWORD}).status_code == 409
        with platform_session() as session:
            rows = session.scalars(select(AuditEvent).where(AuditEvent.action.like("integration_%"))).all()
            actions = [r.action for r in rows]
            details = " ".join(r.detail or "" for r in rows)
        assert {"integration_connected", "integration_secret_rotated", "integration_disconnected"} <= set(actions)
        assert body["client_secret"] not in details and rotated.json()["client_secret"] not in details
        assert "staff_reauth_failed" in self._actions()

    @staticmethod
    def _actions():
        with platform_session() as session:
            return [r.action for r in session.scalars(select(AuditEvent))]

    def test_wrong_passwords_count_toward_the_lockout(self, client, admin, monkeypatch):
        monkeypatch.setenv("HOSPITAL_LOGIN_LOCKOUT_ATTEMPTS", "2")
        assert connect(client, admin, password="wrong-1").status_code == 400
        assert connect(client, admin, password="wrong-2").status_code == 401  # locked out: signed out
        assert client.get("/connections", headers=admin).status_code == 401

    def test_advanced_settings(self, client, admin):
        cid = connected(client, admin)["connection"]["id"]
        resp = client.post(f"/connections/{cid}/ip-restriction", headers=admin,
                           json={"allowed_ips": ["203.0.113.7", "198.51.100.0/24"], "password": PASSWORD})
        assert resp.json()["connection"]["allowed_ips"] == ["203.0.113.7/32", "198.51.100.0/24"]
        assert client.post(f"/connections/{cid}/ip-restriction", headers=admin,
                           json={"allowed_ips": ["not-an-ip"], "password": PASSWORD}).status_code == 400
        hook = client.post(f"/connections/{cid}/webhook", headers=admin,
                           json={"url": "https://hooks.example.com/endod", "password": PASSWORD}).json()
        assert hook["webhook_secret"].startswith("whsec_") and "webhooks" in hook["connection"]["scopes"]
        again = client.post(f"/connections/{cid}/webhook/rotate-secret", headers=admin, json={"password": PASSWORD})
        assert again.json()["webhook_secret"] != hook["webhook_secret"]
        test = client.post(f"/connections/{cid}/webhook/test", headers=admin, json={})
        assert test.status_code == 202
        deliveries = client.get(f"/connections/{cid}/deliveries", headers=admin).json()["items"]
        assert [d["event_type"] for d in deliveries] == ["endpoint.test"] and "body" not in deliveries[0]
        removed = client.post(f"/connections/{cid}/webhook", headers=admin, json={"url": None, "password": PASSWORD})
        assert removed.json()["connection"]["webhook_url"] is None
        assert "webhooks" not in removed.json()["connection"]["scopes"]
        private = {"keys": [{"kty": "EC", "crv": "P-256", "x": "a" * 43, "y": "b" * 43, "d": "c" * 43}]}
        refused = client.post(f"/connections/{cid}/public-key", headers=admin, json={"jwks": private, "password": PASSWORD})
        assert refused.status_code == 400 and "PRIVATE" in refused.json()["error"]


# --- tokens ------------------------------------------------------------------------------------

def _claims(token):
    return json.loads(jose.b64decode(token.split(".")[1]))


class TestTokens:
    def test_client_secret_basic_and_post(self, client, conn, hospital):
        resp = token_request(client, headers=basic(conn["connection"]["client_id"], conn["client_secret"]))
        assert resp.status_code == 200 and resp.headers["cache-control"] == "no-store"
        body = resp.json()
        assert body["token_type"] == "Bearer" and body["expires_in"] == 300
        assert set(body["scope"].split()) == set(ALL_RECORDS)
        claims = _claims(body["access_token"])
        assert claims["exp"] - claims["iat"] == 300 and claims["aud"] == tokens.public_url()
        assert claims["hospital_id"] == hospital and claims["client_id"] == conn["connection"]["client_id"]
        # Signed ES256 with the key published at /.well-known/jwks.json, named by its kid.
        jwks = client.get(f"{API}/.well-known/jwks.json").json()
        keys = jose.parse_jwks(jwks)
        parsed = jose.verify(body["access_token"], keys)
        assert parsed.header["alg"] == "ES256" and parsed.header["kid"] == jwks["keys"][0]["kid"]
        posted = token_request(client, {"client_id": conn["connection"]["client_id"],
                                        "client_secret": conn["client_secret"], "scope": "records.labs.write"})
        assert posted.status_code == 200 and posted.json()["scope"] == "records.labs.write"

    def test_wrong_or_unknown_credentials(self, client, conn):
        cid = conn["connection"]["client_id"]
        for headers in (basic(cid, "wrong-secret"), basic("endod_live_unknown", conn["client_secret"])):
            resp = token_request(client, headers=headers)
            assert resp.status_code == 401 and resp.json()["error"] == "invalid_client"
        assert token_request(client, {"grant_type": "password"}).status_code == 400
        assert token_request(client).status_code == 401  # no credentials at all

    def test_scopes_not_granted_are_refused(self, client, admin):
        conn = connected(client, admin, scopes=["records.labs.write"])
        resp = token_request(client, {"scope": "records.labs.write bookings.read"},
                             basic(conn["connection"]["client_id"], conn["client_secret"]))
        assert resp.status_code == 400 and resp.json()["error"] == "invalid_scope"

    def test_revoked_clients_stop_at_once(self, client, admin, conn, auth):
        assert client.get(f"{API}/bookings", headers=auth).status_code == 403  # no bookings.read: but valid
        client.post(f"/connections/{conn['connection']['id']}/disconnect", headers=admin, json={"password": PASSWORD})
        resp = token_request(client, headers=basic(conn["connection"]["client_id"], conn["client_secret"]))
        assert resp.status_code == 401 and resp.json()["error"] == "invalid_client"
        refused = post_bundle(client, auth, [entry(observation())])
        assert refused.status_code == 401 and refused.json()["resourceType"] == "OperationOutcome"

    def test_a_rotated_secret_ends_older_tokens(self, client, admin, conn, auth):
        client.post(f"/connections/{conn['connection']['id']}/rotate-secret", headers=admin,
                    json={"password": PASSWORD})
        assert post_bundle(client, auth, [entry(observation())]).status_code == 401
        assert token_request(client, headers=basic(conn["connection"]["client_id"],
                                                   conn["client_secret"])).status_code == 401

    def test_ip_restriction(self, client, admin, conn, monkeypatch):
        monkeypatch.setenv("HOSPITAL_TRUSTED_PROXY_HOPS", "1")
        client.post(f"/connections/{conn['connection']['id']}/ip-restriction", headers=admin,
                    json={"allowed_ips": ["203.0.113.0/24"], "password": PASSWORD})
        creds = basic(conn["connection"]["client_id"], conn["client_secret"])
        outside = token_request(client, headers={**creds, "X-Forwarded-For": "198.51.100.9"})
        assert outside.status_code == 401 and "address" in outside.json()["error_description"]
        inside = token_request(client, headers={**creds, "X-Forwarded-For": "203.0.113.9"})
        assert inside.status_code == 200
        auth = {"Authorization": f"Bearer {inside.json()['access_token']}"}
        moved = post_bundle(client, {**auth, "X-Forwarded-For": "198.51.100.9"}, [entry(observation())])
        assert moved.status_code == 403

    def test_unapproved_or_suspended_hospitals(self, client, conn, auth, hospital, patient):
        set_status(hospital, status="suspended")
        creds = basic(conn["connection"]["client_id"], conn["client_secret"])
        resp = token_request(client, headers=creds)
        assert resp.status_code == 400 and resp.json()["error"] == "unauthorized_client"
        assert post_bundle(client, auth, [entry(observation())]).status_code == 403  # a token already issued
        set_status(hospital, status="approved", application=ApplicationStatus.SUBMITTED)
        assert token_request(client, headers=creds).json()["error"] == "unauthorized_client"
        set_status(hospital, application=ApplicationStatus.APPROVED)
        assert token_request(client, headers=creds).status_code == 200

    def test_token_requests_are_rate_limited(self, client, conn, monkeypatch):
        monkeypatch.setattr(ratelimit, "TOKENS_PER_CLIENT", ratelimit.Limiter(2, 60))
        creds = basic(conn["connection"]["client_id"], conn["client_secret"])
        assert [token_request(client, headers=creds).status_code for _ in range(3)] == [200, 200, 429]

    def test_a_forged_or_foreign_token_is_refused(self, client, auth):
        other = ec.generate_private_key(ec.SECP256R1())
        real = auth["Authorization"].split()[1]
        header = json.loads(jose.b64decode(real.split(".")[0]))
        forged = jose.sign_es256(other, {"kid": header["kid"], "typ": "at+jwt"}, _claims(real))
        resp = post_bundle(client, {"Authorization": f"Bearer {forged}"}, [entry(observation())])
        assert resp.status_code == 401
        assert post_bundle(client, {}, [entry(observation())]).status_code == 401


# --- private_key_jwt -------------------------------------------------------------------------------

class KeyClient:
    """A client using public-key authentication (SMART Backend Services)."""

    def __init__(self, client, admin, conn, kind="EC"):
        self.client, self.client_id = client, conn["connection"]["client_id"]
        if kind == "EC":
            self.key = ec.generate_private_key(ec.SECP256R1())
            jwk = jose.ec_public_jwk(self.key.public_key(), kid="k1")
        else:
            self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            jwk = jose.rsa_public_jwk(self.key.public_key(), kid="k1")
        self.kind = kind
        resp = client.post(f"/connections/{conn['connection']['id']}/public-key", headers=admin,
                           json={"jwks": json.dumps({"keys": [jwk]}), "password": PASSWORD})
        assert resp.status_code == 200, resp.text
        assert resp.json()["connection"]["auth_method"] == "private_key_jwt"

    def assertion(self, **changes):
        now = int(time.time())
        claims = {"iss": self.client_id, "sub": self.client_id, "aud": tokens.token_url(), "exp": now + 240,
                  "iat": now, "jti": uuid.uuid4().hex}
        claims.update(changes)
        claims = {k: v for k, v in claims.items() if v is not None}
        sign = jose.sign_es256 if self.kind == "EC" else jose.sign_rs256
        return sign(self.key, {"kid": "k1", "typ": "JWT"}, claims)

    def request(self, assertion):
        return token_request(self.client, {"client_assertion_type": tokens.ASSERTION_TYPE,
                                           "client_assertion": assertion})


class TestPrivateKeyJwt:
    @pytest.mark.parametrize("kind", ["EC", "RSA"])
    def test_a_signed_assertion_gets_a_token_and_the_secret_stops_working(self, client, admin, conn, kind):
        keys = KeyClient(client, admin, conn, kind)
        assert keys.request(keys.assertion()).status_code == 200
        assert token_request(client, headers=basic(keys.client_id, conn["client_secret"])).status_code == 401

    def test_a_replayed_jti_is_refused(self, client, admin, conn):
        keys = KeyClient(client, admin, conn)
        assertion = keys.assertion()
        assert keys.request(assertion).status_code == 200
        replay = keys.request(assertion)
        assert replay.status_code == 401 and "already used" in replay.json()["error_description"]

    @pytest.mark.parametrize("changes, words", [
        ({"aud": "https://elsewhere.example/token"}, "aud"),
        ({"exp": int(time.time()) - 600}, "expired"),
        ({"exp": int(time.time()) + 3600}, "5 minutes"),
        ({"exp": None}, "exp"),
        ({"jti": None}, "jti"),
        ({"sub": "someone-else"}, "sub"),
    ])
    def test_bad_assertions(self, client, admin, conn, changes, words):
        keys = KeyClient(client, admin, conn)
        resp = keys.request(keys.assertion(**changes))
        assert resp.status_code == 401 and words in resp.json()["error_description"], resp.text

    def test_an_assertion_signed_by_another_key(self, client, admin, conn):
        keys = KeyClient(client, admin, conn)
        keys.key = ec.generate_private_key(ec.SECP256R1())
        assert keys.request(keys.assertion()).status_code == 401


# --- FHIR writes ------------------------------------------------------------------------------------

DOCUMENT = {"resourceType": "DocumentReference", "status": "current", "subject": subject(),
            "description": "Discharge summary", "date": "2026-10-02T10:00:00+03:00",
            "content": [{"attachment": {"contentType": "application/pdf", "title": "summary.pdf",
                                        "data": base64.b64encode(PDF).decode()}}]}


def resources():
    """One of each accepted resource, for the patient SPH-000001."""
    return {
        "Observation": (observation(), "lab_result", "Hemoglobin"),
        "DiagnosticReport (lab)": ({
            "resourceType": "DiagnosticReport", "status": "final", "subject": subject(),
            "category": [{"coding": [{"code": "LAB"}]}], "code": {"text": "Complete blood count"},
            "effectiveDateTime": "2026-10-01T09:00:00+03:00", "conclusion": "Within normal limits",
            "contained": [observation("WBC", 6.1), observation("Platelets", 250)]}, "lab_result",
            "Complete blood count"),
        "DiagnosticReport (imaging)": ({
            "resourceType": "DiagnosticReport", "status": "final", "subject": subject(),
            "category": [{"coding": [{"code": "RAD"}, {"code": "CT", "display": "CT"}]}],
            "code": {"text": "CT head"}, "conclusion": "No bleed", "issued": "2026-10-01T11:00:00+03:00"},
            "imaging", "CT head"),
        "MedicationRequest": ({
            "resourceType": "MedicationRequest", "status": "active", "intent": "order", "subject": subject(),
            "medicationCodeableConcept": {"text": "Amoxicillin 500 mg"}, "authoredOn": "2026-10-01",
            "dosageInstruction": [{"text": "1 capsule three times a day"}]}, "prescription",
            "Prescription: Amoxicillin 500 mg"),
        "Condition": ({
            "resourceType": "Condition", "subject": subject(), "code": {
                "text": "Malaria", "coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "B54"}]},
            "clinicalStatus": {"coding": [{"code": "active"}]}, "recordedDate": "2026-10-01"}, "diagnosis", "Malaria"),
        "Encounter": ({
            "resourceType": "Encounter", "status": "finished", "class": {"code": "AMB", "display": "ambulatory"},
            "subject": subject(), "type": [{"text": "Outpatient visit"}], "period": {"start": "2026-10-01T08:00:00Z"},
            "reasonCode": [{"text": "Fever for 3 days"}]}, "visit_note", "Outpatient visit"),
        "DocumentReference": (DOCUMENT, "document", "Discharge summary"),
    }


class TestFhir:
    @pytest.mark.parametrize("name", list(resources()))
    def test_each_resource_becomes_a_record(self, client, auth, patient, name):
        resource, category, title = resources()[name]
        resp = post_bundle(client, auth, [entry(resource)])
        assert resp.status_code == 200, resp.text
        bundle = resp.json()
        assert bundle["type"] == "transaction-response"
        assert bundle["entry"][0]["response"]["status"] == "201 Created"
        stored = records_of(patient)
        assert [(r.category, r.title, r.source) for r in stored] == [(category, title, "import")]
        assert bundle["entry"][0]["response"]["location"].startswith(f"{resource['resourceType']}/{stored[0].id}")
        if category == "document":
            with platform_session() as session:
                assert session.scalar(select(func.count()).where(RecordFile.record_id == stored[0].id)) == 1

    def test_a_single_resource(self, client, auth, patient):
        resp = client.post(f"{API}/fhir/Condition", headers={**auth, "Content-Type": "application/fhir+json"},
                           content=json.dumps(resources()["Condition"][0]))
        assert resp.status_code == 201 and resp.headers["location"].startswith("Condition/")
        assert client.post(f"{API}/fhir/Patient", headers={**auth, "Content-Type": "application/fhir+json"},
                           content=json.dumps({"resourceType": "Patient"})).status_code == 400
        wrong = client.post(f"{API}/fhir/Condition", headers={**auth, "Content-Type": "application/fhir+json"},
                            content=json.dumps(observation()))
        assert wrong.status_code == 400

    def test_records_are_encrypted_and_readable_in_the_portal(self, client, admin, hospital, auth, patient):
        post_bundle(client, auth, [entry(observation(test=f"Glucose {MARK}"))])
        from app.db import get_engine
        with get_engine().connect() as connection:
            from sqlalchemy import text
            raw = connection.execute(text("SELECT title FROM clinical_records")).scalars().all()
        assert raw and all(MARK not in (v or "") for v in raw)  # ciphertext at rest
        make_staff(hospital, "doc@sph.example", role="doctor")
        doctor = sign_in(client, "doc@sph.example")
        items = client.get(f"/patients/{patient}/records", headers=doctor).json()["items"]
        assert items[0]["title"] == f"Glucose {MARK}" and items[0]["details"]["items"][0]["value"] == "13.2"

    def test_patients_by_endod_id_and_bundle_patient(self, client, auth, hospital):
        linked = make_patient(hospital, mrn="SPH-000002", dedan_id="DE123456")
        by_id = observation()
        by_id["subject"] = {"identifier": {"system": ENDOD, "value": "DE123456"}}
        in_bundle = observation(test="Creatinine")
        in_bundle["subject"] = {"reference": "urn:uuid:p1"}
        patient_entry = {"fullUrl": "urn:uuid:p1", "resource": {
            "resourceType": "Patient", "identifier": [{"system": MRN_SYSTEM, "value": "SPH-000002"}],
            "name": [{"text": "Someone Else Entirely"}]}}
        resp = post_bundle(client, auth, [entry(by_id), patient_entry, entry(in_bundle)])
        assert resp.status_code == 200, resp.text
        assert len(records_of(linked)) == 2
        with platform_session() as session:  # never created or changed
            assert session.scalar(select(func.count()).select_from(Patient)) == 2  # SPH-000001 and this one
            assert session.get(Patient, linked).full_name == "Almaz Tefera"

    def test_unknown_patients_never_match_by_name_or_another_system(self, client, auth, patient):
        cases = [observation(mrn="SPH-999999"), observation(system="https://other-hospital.example/mrn")]
        named = observation()
        named["subject"] = {"display": "Almaz Tefera"}
        cases.append(named)
        resp = post_bundle(client, auth, [entry(c) for c in cases], kind="batch")
        statuses = [e["response"]["status"] for e in resp.json()["entry"]]
        assert statuses == ["422 Unprocessable Entity"] * 3
        assert all(e["response"]["outcome"]["resourceType"] == "OperationOutcome" for e in resp.json()["entry"])
        assert records_of(patient) == []

    def test_a_transaction_is_all_or_nothing_and_a_batch_is_not(self, client, auth, patient):
        good, bad = observation(), observation(mrn="SPH-404404")
        resp = post_bundle(client, auth, [entry(good), entry(bad)])
        assert resp.status_code == 422 and resp.json()["issue"][0]["expression"] == ["Bundle.entry[1]"]
        assert records_of(patient) == []
        resp = post_bundle(client, auth, [entry(good), entry(bad)], kind="batch")
        assert [e["response"]["status"][:3] for e in resp.json()["entry"]] == ["201", "422"]
        assert len(records_of(patient)) == 1

    def test_published_to_endod_only_for_linked_patients(self, client, auth, hospital, patient):
        linked = make_patient(hospital, mrn="SPH-000002", dedan_id="DE654321")
        post_bundle(client, auth, [entry(observation()), entry(observation(mrn="SPH-000002"))])
        with platform_session() as session:
            published = [json.loads(e.payload) for e in session.scalars(select(OutboxEvent).where(
                OutboxEvent.type == "record.published"))]
        assert [p["dedan_id"] for p in published] == ["DE654321"]
        assert records_of(linked)[0].published_dedan_id == "DE654321"
        assert records_of(patient)[0].published_dedan_id is None

    def test_corrections_by_resource_id_and_version(self, client, auth, patient):
        first = post_bundle(client, auth, [entry(observation(rid="lab-1", version="1"), "PUT")])
        assert first.json()["entry"][0]["response"]["status"] == "201 Created"
        same = post_bundle(client, auth, [entry(observation(rid="lab-1", version="1", value=99), "PUT")])
        assert same.json()["entry"][0]["response"]["status"] == "200 OK"  # the same version: unchanged
        corrected = post_bundle(client, auth, [entry(observation(rid="lab-1", version="2", value=14.0), "PUT")])
        assert corrected.json()["entry"][0]["response"]["etag"] == 'W/"2"'
        stored = records_of(patient)
        assert len(stored) == 1 and stored[0].version == 2
        assert json.loads(stored[0].details)["items"][0]["value"] == "14.0"
        # Without an id, the same content twice is one record.
        post_bundle(client, auth, [entry(observation(test="Sodium"))])
        again = post_bundle(client, auth, [entry(observation(test="Sodium"))])
        assert again.json()["entry"][0]["response"]["status"] == "200 OK"
        assert len(records_of(patient)) == 2

    def test_idempotency_key_replays_the_first_answer(self, client, auth, patient):
        key = {"Idempotency-Key": "batch-2026-10-01-0001"}
        first = post_bundle(client, auth, [entry(observation())], headers=key)
        again = post_bundle(client, auth, [entry(observation())], headers=key)
        assert again.json() == first.json() and again.headers.get("idempotent-replayed") == "true"
        assert len(records_of(patient)) == 1
        other = post_bundle(client, auth, [entry(observation(test="Potassium"))], headers=key)
        assert other.status_code == 422 and "Idempotency-Key" in other.json()["issue"][0]["diagnostics"]
        with platform_session() as session:  # the stored answer is encrypted at rest
            raw = session.connection().exec_driver_sql("SELECT response FROM integration_idempotency").scalar()
        assert raw.startswith("enc:v1:")

    def test_test_mode_stores_nothing(self, client, admin, patient):
        conn = connected(client, admin, mode="test")
        assert conn["connection"]["client_id"].startswith("endod_test_")
        auth = get_token(client, conn)
        before = count(AuditEvent)
        resp = post_bundle(client, auth, [entry(r) for r, _c, _t in resources().values()])
        assert resp.status_code == 200, resp.text
        bundle = resp.json()
        assert bundle["meta"]["tag"][0]["code"] == "test-mode"
        assert {e["response"]["status"] for e in bundle["entry"]} == {"201 Created"}
        assert "would create" in bundle["entry"][0]["response"]["outcome"]["issue"][0]["diagnostics"]
        assert records_of(patient) == [] and count(RecordFile) == 0 and count(IntegrationResource) == 0
        assert count(OutboxEvent) == 0 and count(AuditEvent) == before
        bad = post_bundle(client, auth, [entry(observation(mrn="SPH-404404"))])
        assert bad.status_code == 422  # validated all the same

    def test_scopes_per_resource(self, client, admin, patient):
        auth = get_token(client, connected(client, admin, scopes=["records.labs.write"]))
        resp = post_bundle(client, auth, [entry(r) for r, _c, _t in resources().values()], kind="batch")
        statuses = [e["response"]["status"][:3] for e in resp.json()["entry"]]
        assert statuses == ["201", "201", "403", "403", "403", "403", "403"]
        assert client.get(f"{API}/bookings", headers=auth).status_code == 403
        only_bookings = get_token(client, connected(client, admin, scopes=["bookings.read"], name="Desk"))
        assert post_bundle(client, only_bookings, [entry(observation())]).status_code == 403

    def test_documents_are_magic_checked(self, client, auth, patient):
        fake = json.loads(json.dumps(DOCUMENT))
        fake["content"][0]["attachment"]["data"] = base64.b64encode(b"MZ\x90\x00 not a pdf").decode()
        resp = post_bundle(client, auth, [entry(fake)])
        assert resp.status_code == 422 and "PDF" in resp.json()["issue"][0]["diagnostics"]

    def test_limits(self, client, auth, patient, monkeypatch):
        many = post_bundle(client, auth, [entry(observation(test=f"T{i}")) for i in range(101)])
        assert many.status_code == 413
        from app.integrations import fhir
        monkeypatch.setattr(fhir, "MAX_BODY_BYTES", 2000)
        big = post_bundle(client, auth, [entry(observation(test="x" * 3000))])
        assert big.status_code == 413
        assert client.post(f"{API}/fhir", headers={**auth, "Content-Type": "text/plain"},
                           content="{}").status_code == 415
        monkeypatch.setattr(ratelimit, "REQUESTS_PER_CLIENT", ratelimit.Limiter(2, 60))
        codes = [post_bundle(client, auth, [entry(observation())]).status_code for _ in range(3)]
        assert codes[-1] == 429

    def test_writes_are_audited_without_clinical_values(self, client, auth, conn, patient):
        post_bundle(client, auth, [entry(observation(test=f"HIV viral load {MARK}"))])
        with platform_session() as session:
            row = session.scalar(select(AuditEvent).where(AuditEvent.action == "integration_record_created"))
        detail = json.loads(row.detail)
        assert detail["client_id"] == conn["connection"]["client_id"] and detail["record_id"]
        assert row.target_id == patient and MARK not in row.detail and "HIV" not in row.detail


# --- cross-hospital isolation -------------------------------------------------------------------------

class TestIsolation:
    def test_a_client_of_one_hospital_cannot_reach_another(self, client, auth, hospital, patient):
        other = make_hospital(code="BET", name="Bethel Hospital")
        theirs = make_patient(other, mrn="BET-000001", dedan_id="DE777777")
        attempts = [observation(mrn="BET-000001", system="https://endod-health.com/hospital/bet/mrn"),
                    observation(mrn="BET-000001")]
        by_endod = observation()
        by_endod["subject"] = {"identifier": {"system": ENDOD, "value": "DE777777"}}
        attempts.append(by_endod)
        resp = post_bundle(client, auth, [entry(a) for a in attempts], kind="batch")
        assert [e["response"]["status"][:3] for e in resp.json()["entry"]] == ["422"] * 3
        assert records_of(theirs) == []

    def test_bookings_are_the_hospitals_own(self, client, admin, hospital):
        other = make_hospital(code="BET", name="Bethel Hospital")
        mine, theirs = book(hospital), book(other)
        auth = get_token(client, connected(client, admin, scopes=["bookings.read"]))
        items = client.get(f"{API}/bookings", headers=auth).json()["items"]
        assert [b["id"] for b in items] == [mine]
        assert "notes" not in items[0] and items[0]["patient"]["endod_id"] == "DE123456"
        assert client.get(f"{API}/bookings/{theirs}", headers=auth).status_code == 404
        assert client.get(f"{API}/bookings/{mine}", headers=auth).status_code == 200

    def test_connections_are_the_hospitals_own(self, client, admin, conn):
        other = make_hospital(code="BET", name="Bethel Hospital")
        make_staff(other, "admin@bet.example", role="admin")
        theirs = sign_in(client, "admin@bet.example")
        cid = conn["connection"]["id"]
        assert client.get("/connections", headers=theirs).json()["items"] == []
        assert client.get(f"/connections/{cid}", headers=theirs).status_code == 404
        assert client.post(f"/connections/{cid}/disconnect", headers=theirs,
                           json={"password": PASSWORD}).status_code == 404


def book(hospital_id, mode="in_person"):
    payload = {"appointment_id": uuid.uuid4().hex, "hospital_id": hospital_id,
               "patient": {"dedan_id": "DE123456", "name": "Almaz Tefera", "phone": "+251911234567"},
               "visit_mode": mode, "service": "general_medicine",
               "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
               "duration_minutes": 30, "notes": f"Headache {MARK}", "price": 15000}
    with platform_session() as session:
        bookings.on_requested(session, payload)
    with platform_session() as session:
        return session.scalar(select(Booking.id).where(Booking.external_id == payload["appointment_id"]))


# --- webhooks -----------------------------------------------------------------------------------------

class TestWebhooks:
    def test_signature_like_stripe(self):
        body = b'{"id":"evt_1"}'
        header = webhooks.signature_header("whsec_test", 1700000000, body)
        t, v1 = header.split(",")
        assert t == "t=1700000000" and len(v1) == 3 + 64
        import hashlib
        import hmac
        assert v1[3:] == hmac.new(b"whsec_test", b"1700000000." + body, hashlib.sha256).hexdigest()
        assert webhooks.verify("whsec_test", header, body, now=1700000100)
        assert not webhooks.verify("whsec_test", header, body + b" ", now=1700000100)
        assert not webhooks.verify("whsec_test", header, body, now=1700001000)  # too old

    @pytest.mark.parametrize("url", [
        "http://hooks.example.com/x", "https://localhost/x", "https://127.0.0.1/x", "https://10.1.2.3/x",
        "https://169.254.169.254/latest", "https://[::1]/x", "https://192.168.1.10/x", "https://user:pw@hooks.example.com/",
        "https://intranet/x", "https://100.64.0.1/x", "https://[::ffff:10.0.0.1]/x",
    ])
    def test_unsafe_addresses_are_refused_when_set(self, url):
        with pytest.raises(clients.WebhookUrlError):
            clients.check_webhook_url(url)

    def test_dns_is_checked_at_send_time_and_redirects_are_not_followed(self, monkeypatch):
        import socket
        answers = {"evil.example.com": "10.0.0.5", "meta.example.com": "169.254.169.254",
                   "good.example.com": "93.184.216.34"}
        monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **_kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (answers[host], port))])
        for host in ("evil.example.com", "meta.example.com"):
            sent = webhooks.post(f"https://{host}/hook", {}, b"{}")
            assert not sent.ok and sent.error.startswith("blocked")
        assert webhooks.destination("https://good.example.com/hook?a=1")[2] == "/hook?a=1"
        with pytest.raises(webhooks.Blocked):
            webhooks.destination("http://good.example.com/hook")

    def test_booking_events_are_signed_delivered_and_forgotten(self, client, admin, hospital, monkeypatch):
        conn = connected(client, admin, scopes=["bookings.read", "webhooks"],
                         webhook_url="https://hooks.example.com/endod")
        sent = []

        def fake_post(url, headers, body):
            sent.append((url, headers, body))
            return webhooks.Sent(True, 200, None)

        monkeypatch.setattr(webhooks, "post", fake_post)
        booking_id = book(hospital)
        assert webhooks.deliver_due() == 2  # booking.created and booking.confirmed (in person)
        events = [json.loads(body) for _u, _h, body in sent]
        assert [e["type"] for e in events] == ["booking.created", "booking.confirmed"]
        assert events[0]["data"]["booking_id"] == booking_id and MARK not in json.dumps(events)
        for _url, headers, body in sent:
            assert webhooks.verify(conn["webhook_secret"], headers["Endod-Signature"], body)
        with platform_session() as session:
            rows = session.scalars(select(WebhookDelivery)).all()
        assert {(r.status, r.body) for r in rows} == {(DeliveryStatus.DELIVERED, None)}

    def test_failures_are_retried_with_backoff_then_given_up(self, client, admin, hospital, monkeypatch):
        connected(client, admin, scopes=["webhooks"], webhook_url="https://hooks.example.com/endod")
        monkeypatch.setattr(webhooks, "post", lambda *_a: webhooks.Sent(False, 500, "answered 500"))
        with platform_session() as session:
            from app.models import Patient as P
            patient = P(hospital_id=hospital, mrn="SPH-000009", full_name="X", sex="male", dedan_id="DE111111")
            session.add(patient)
            session.flush()
            from app import linking
            linking.unlink(session, patient)
        assert webhooks.deliver_due() == 1
        with platform_session() as session:
            row = session.scalar(select(WebhookDelivery))
            assert row.event_type == "patient.unlinked" and row.attempts == 1 and row.status == "pending"
            assert row.body is not None and row.last_status_code == 500
            first_retry = row.next_attempt_at
        assert webhooks.deliver_due() == 0  # not due yet
        later = datetime.now(timezone.utc) + timedelta(hours=25)
        assert webhooks.deliver_due(now=later) == 1
        with platform_session() as session:
            row = session.scalar(select(WebhookDelivery))
            assert row.status == "failed" and row.body is None and row.attempts == 2 and first_retry is not None

    def test_disconnected_or_suspended_get_nothing(self, client, admin, hospital, monkeypatch):
        conn = connected(client, admin, scopes=["webhooks"], webhook_url="https://hooks.example.com/endod")
        monkeypatch.setattr(webhooks, "post", lambda *_a: pytest.fail("must not send"))
        book(hospital)
        set_status(hospital, status="suspended")
        webhooks.deliver_due()
        set_status(hospital, status="approved")
        client.post(f"/connections/{conn['connection']['id']}/disconnect", headers=admin, json={"password": PASSWORD})
        book(hospital)
        webhooks.deliver_due()
        with platform_session() as session:
            assert {r.status for r in session.scalars(select(WebhookDelivery))} == {"failed"}


# --- the request log, docs ---------------------------------------------------------------------------

class TestRequestLog:
    def test_calls_are_logged_without_bodies(self, client, admin, conn, auth, patient, caplog):
        caplog.set_level("INFO")
        post_bundle(client, auth, [entry(observation(test=f"Glucose {MARK}"))])
        post_bundle(client, auth, [entry(observation(mrn="SPH-404404", test=MARK))])
        rows = client.get(f"/connections/{conn['connection']['id']}/requests", headers=admin).json()["items"]
        assert [(r["method"], r["path"], r["status"]) for r in rows[:2]] == [
            ("POST", f"{API}/fhir", 422), ("POST", f"{API}/fhir", 200)]
        assert any(r["path"] == f"{API}/oauth/token" for r in rows)
        assert set(rows[0]) == {"at", "method", "path", "status", "duration_ms", "ip"}
        with platform_session() as session:
            stored = json.dumps([[getattr(r, c.name) for c in IntegrationRequest.__table__.columns]
                                 for r in session.scalars(select(IntegrationRequest))], default=str)
        assert MARK not in stored and conn["client_secret"] not in stored
        assert MARK not in caplog.text and conn["client_secret"] not in caplog.text

    def test_old_entries_are_removed(self, client, conn, auth, patient):
        from app import chores
        post_bundle(client, auth, [entry(observation())])
        with platform_session() as session:
            for row in session.scalars(select(IntegrationRequest)):
                row.at = datetime.now(timezone.utc) - timedelta(days=31)
        chores.run()
        assert count(IntegrationRequest) == 0


class TestDocs:
    def test_openapi_jwks_and_guide(self, client):
        schema = client.get(f"{API}/openapi.json").json()
        assert schema["info"]["title"] == "Endod Hospital Integration API"
        assert {"/oauth/token", "/fhir", "/fhir/{resource_type}", "/bookings"} <= set(schema["paths"])
        flows = schema["components"]["securitySchemes"]["endod"]["flows"]["clientCredentials"]
        assert flows["tokenUrl"] == tokens.token_url() and "records.labs.write" in flows["scopes"]
        assert "openapi.json" in client.get(f"{API}/docs").text
        assert client.get(f"{API}/.well-known/jwks.json").json()["keys"][0]["alg"] == "ES256"

    def test_the_served_guide_is_docs_integrations_md(self):
        root = Path(__file__).resolve().parents[2]
        served = root / "backend-hospital" / "app" / "integrations" / "guide.md"
        assert served.read_text(encoding="utf-8") == (root / "docs" / "integrations.md").read_text(encoding="utf-8")


def test_the_signing_key_comes_from_its_file(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    key = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path / "signing.pem"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    monkeypatch.setenv("HOSPITAL_INTEGRATIONS_SIGNING_KEY_FILE", str(path))
    signing.clear_cache()
    try:
        assert signing.signing_key().kid == jose.thumbprint(jose.ec_public_jwk(key.public_key()))
        monkeypatch.setenv("HOSPITAL_INTEGRATIONS_SIGNING_KEY_FILE", str(tmp_path / "missing.pem"))
        with pytest.raises(signing.SigningKeyMissing):
            signing.signing_key()
        monkeypatch.delenv("HOSPITAL_INTEGRATIONS_SIGNING_KEY_FILE")
        monkeypatch.setenv("HOSPITAL_ENVIRONMENT", "production")
        with pytest.raises(signing.SigningKeyMissing):  # never a made-up key in production
            signing.signing_key()
    finally:
        signing.clear_cache()


def test_secrets_are_long_and_random():
    assert len(clients.new_secret()) >= 40 and clients.new_secret() != clients.new_secret()
    assert clients.verify_secret("x", None) is False
    hashed = clients.hash_secret("abc")
    assert clients.verify_secret("abc", hashed) and not clients.verify_secret("abd", hashed)
