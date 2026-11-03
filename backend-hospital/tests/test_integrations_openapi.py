"""The integration API's OpenAPI document documents everything it serves:
every route (summary, scope, request examples, answers), every scope, every
webhook event; and it is a valid OpenAPI 3.1 document."""

import pytest
from fastapi.routing import APIRoute

from app.api import integrations
from app.integrations import fhir, schemas, scopes, webhooks

PUBLIC = {"/oauth/token", "/.well-known/jwks.json"}


@pytest.fixture(scope="module")
def app():
    return integrations.create_app()


@pytest.fixture(scope="module")
def spec(app):
    return app.openapi()


def documented_routes(app):
    return [r for r in app.routes if isinstance(r, APIRoute) and r.include_in_schema]


def test_every_route_is_documented(app, spec):
    routes = documented_routes(app)
    assert len(routes) >= 29
    for route in routes:
        for method in route.methods:
            operation = spec["paths"][route.path][method.lower()]
            where = f"{method} {route.path}"
            assert operation.get("summary"), where
            assert operation.get("tags"), where
            assert operation.get("description"), where
            if route.path in PUBLIC:
                assert operation["security"] == [], where
            else:
                assert operation["security"], where
                for requirement in operation["security"]:
                    assert all(s in scopes.SCOPES for s in requirement["endod"]), where
                for status in ("401", "403", "429"):
                    assert status in operation["responses"], where
            body = operation.get("requestBody")
            if body is not None:
                assert any("example" in c or "examples" in c for c in body["content"].values()), where
            successes = [code for code in operation["responses"] if code.startswith("2")]
            assert successes, where
            for code, response in operation["responses"].items():
                assert response.get("description"), (where, code)
                if code.startswith("4") and route.path not in PUBLIC:
                    [content] = response["content"].values()
                    assert content["schema"] == {"$ref": "#/components/schemas/OperationOutcome"}, (where, code)


VIDEO_ONLY = {"/bookings/{booking_id}/approve", "/bookings/{booking_id}/decline"}


def test_hidden_routes_are_only_the_docs_the_fallback_and_video_visits(app, spec):
    """Video visits are off by default (HOSPITAL_VIDEO_VISITS_ENABLED): approving
    and declining them are left out of the document (and answer 404)."""
    hidden = {r.path for r in app.routes if isinstance(r, APIRoute) and not r.include_in_schema}
    assert hidden == {"/docs", "/fhir/{resource_type}"} | VIDEO_ONLY
    assert not VIDEO_ONLY & set(spec["paths"])
    assert "video" not in spec["info"]["description"].split("---")[0]


def test_video_visits_on_are_documented(monkeypatch):
    monkeypatch.setenv("HOSPITAL_VIDEO_VISITS_ENABLED", "true")
    app = integrations.create_app()
    hidden = {r.path for r in app.routes if isinstance(r, APIRoute) and not r.include_in_schema}
    assert hidden == {"/docs", "/fhir/{resource_type}"}
    spec = app.openapi()
    assert VIDEO_ONLY <= set(spec["paths"])
    assert "approve or decline video visits" in spec["info"]["description"]


def test_pricing_is_documented(spec):
    assert "Pricing" in {t["name"] for t in spec["tags"]}
    for path, method, scope in (("/prices", "get", "prices.read"), ("/prices/consultation", "put", "prices.write"),
                                ("/prices/lab-tests", "put", "prices.write"), ("/prices/imaging", "put", "prices.write"),
                                ("/prices/procedures", "put", "prices.write")):
        operation = spec["paths"][path][method]
        assert operation["tags"] == ["Pricing"], path
        assert {"endod": [scope]} in operation["security"], path
        assert operation["responses"]["200"]["content"]["application/json"]["example"], path
        if method == "put":
            examples = operation["requestBody"]["content"]["application/json"]["examples"]
            assert examples, path
    flow = spec["components"]["securitySchemes"]["endod"]["flows"]["clientCredentials"]
    assert {"prices.read", "prices.write"} <= set(flow["scopes"])


def test_each_fhir_resource_has_its_own_operation(spec):
    for kind in fhir.SUPPORTED:
        operation = spec["paths"][f"/fhir/{kind}"]["post"]
        content = operation["requestBody"]["content"]["application/fhir+json"]
        assert content["schema"] == {"$ref": f"#/components/schemas/Fhir{kind}"}
        assert content["examples"]
        for status in ("200", "201", "400", "401", "403", "409", "413", "415", "422", "429"):
            assert status in operation["responses"], (kind, status)
    examples = spec["paths"]["/fhir/DiagnosticReport"]["post"]["requestBody"]["content"]["application/fhir+json"]
    assert set(examples["examples"]) == {"lab_panel", "imaging"}
    bundle = spec["paths"]["/fhir"]["post"]
    assert set(bundle["requestBody"]["content"]["application/fhir+json"]["examples"]) == {"transaction", "batch"}
    assert spec["paths"]["/fhir/{resource_type}/{resource_id}"]["get"]["security"]


def test_security_scheme_lists_every_scope(spec):
    scheme = spec["components"]["securitySchemes"]["endod"]
    flow = scheme["flows"]["clientCredentials"]
    assert set(flow["scopes"]) == set(scopes.SCOPES)
    assert all(flow["scopes"][s] for s in scopes.SCOPES)
    assert "private_key_jwt" in scheme["description"]


def test_webhooks_list_every_event(spec):
    events = set(webhooks.EVENTS) | {webhooks.TEST_EVENT}
    assert set(spec["webhooks"]) == events
    assert set(schemas.WEBHOOK_EVENTS) == events
    for event in events:
        operation = spec["webhooks"][event]["post"]
        content = operation["requestBody"]["content"]["application/json"]
        assert content["example"]["type"] == event and content["schema"]["$ref"].startswith("#/components/schemas/")
        assert "Endod-Signature" in {p["name"] for p in operation["parameters"]}
        assert "HMAC-SHA256" in operation["description"] and "24 hours" in operation["description"]


def test_overview_tags_and_servers(spec):
    assert spec["openapi"].startswith("3.1")
    assert spec["servers"] == [{"url": integrations.tokens.public_url()}]
    assert [t["name"] for t in spec["tags"]][:3] == ["Authentication", "Records (FHIR)", "Patients"]
    assert {"Bookings", "Follow-ups", "Prescriptions", "Webhooks"} <= {t["name"] for t in spec["tags"]}
    assert "Hospitals keep their own EMR" in spec["info"]["description"]
    assert "integrations.md" in spec["externalDocs"]["url"]
    assert "HTTPValidationError" not in spec["components"]["schemas"]


def test_the_document_is_valid_openapi(spec):
    validator = pytest.importorskip("openapi_spec_validator")
    validator.validate(spec)


def test_served_at_openapi_json(db):
    from fastapi.testclient import TestClient

    from app import integrations_main

    served = TestClient(integrations_main.create_app()).get("/integrations/v1/openapi.json").json()
    assert "/patients" in served["paths"] and "prescription.dispensed" in served["webhooks"]


def test_charges_are_documented(spec):
    assert "Charges" in {t["name"] for t in spec["tags"]}
    for path, method, scopes_needed in (
            ("/charges", "post", ["charges.write"]), ("/charges", "get", ["charges.read", "charges.write"]),
            ("/charges/{charge_id}", "get", ["charges.read", "charges.write"]),
            ("/charges/{charge_id}/paid", "post", ["charges.write"]),
            ("/charges/{charge_id}/void", "post", ["charges.write"]),
            ("/service-fee", "get", ["charges.read", "charges.write", "bookings.read"]),
            ("/bookings/{booking_id}/paid", "post", ["bookings.write"])):
        operation = spec["paths"][path][method]
        assert [{"endod": [s]} for s in scopes_needed] == operation["security"], path
        [success] = [c for c in operation["responses"] if c.startswith("2")]
        assert operation["responses"][success]["content"]["application/json"]["example"], path
        if method == "post":
            assert operation["requestBody"]["content"]["application/json"]["examples"], path
    assert "once per charge" in spec["paths"]["/charges"]["post"]["description"]
    flow = spec["components"]["securitySchemes"]["endod"]["flows"]["clientCredentials"]
    assert {"charges.read", "charges.write"} <= set(flow["scopes"])
    assert {"charge.created", "charge.paid", "charge.voided"} <= set(spec["webhooks"])
