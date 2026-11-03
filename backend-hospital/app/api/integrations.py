"""The integration API, served under /integrations/v1 (published by nginx at
HOSPITAL_INTEGRATIONS_PUBLIC_URL, e.g. https://api.endod-health.com/hospital/v1).

A FastAPI application of its own, run by its own service (the
``integrations`` service, app/integrations_main.py: the only one on the
shared edge network, and the only one with the token signing key), so it has its own
OpenAPI document (``/openapi.json``: every endpoint, scope, request and
answer with examples, and every webhook event), its own docs page
(``/docs``, with the guide, docs/integrations.md) and its own errors: OAuth
errors from the token endpoint, FHIR OperationOutcomes everywhere else.
Every call is written to the request log (method, path, status, client,
time, duration, address; never a body), once the client is known.

The routes: authentication and FHIR records here; the patient journey
(patients, bookings, doctors, follow-ups, prescriptions, the queue) in
app/integrations/journey.py.

Only nginx reaches it: every request must carry ``X-Endod-Edge-Key`` (the
shared EDGE_SHARED_SECRET, compared in constant time; without one configured,
production answers 503). The caller's address is taken ONLY from
``X-Endod-Client-IP``, which nginx sets; X-Forwarded-For is ignored.
"""

from __future__ import annotations

import copy
import hmac
import html
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, Header, Request
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from starlette.exceptions import HTTPException

from app.config import get_settings
from app.db import ensure_aware, session_scope
from app.integrations import (
    apidoc as D, charges, fhir, fhir_docs as F, journey, pricing, scopes as S, schemas as M, signing, tokens,
)
from app.integrations import webhooks
from app.integrations.calls import (
    CLIENT_IP_HEADER, FHIR_JSON, caller, client_address, is_test, outcome_response as _outcome_response, via,
)
from app.integrations.tokens import Caller
from app.models import (
    AuditEvent, ClinicalRecord, Hospital, IntegrationRequest, IntegrationResource, Patient, RecordCategory,
)
from app import records
from app.auth import audit

logger = logging.getLogger("hospital.integrations")

PREFIX = "/integrations/v1"
MAX_TOKEN_REQUEST = 16 * 1024
GUIDE = Path(__file__).resolve().parents[1] / "integrations" / "guide.md"
RECORD_SCOPES = S.RECORDS
EDGE_KEY_HEADER = "x-endod-edge-key"
GUIDE_URL = "https://github.com/Dan12-dev-ai/Hospital-service/blob/main/docs/integrations.md"

__all__ = ["PREFIX", "create_app", "client_address", "edge_refusal", "CLIENT_IP_HEADER"]


def edge_refusal(request: Request) -> Optional[JSONResponse]:
    """None if the request came through nginx (the edge key matches); else the refusal."""
    settings = get_settings()
    key = settings.EDGE_SHARED_SECRET
    if not key:
        if settings.is_production:
            return _outcome_response(503, "transient", "The integration API is not available.")
        return None  # development and tests: no edge in front
    given = request.headers.get(EDGE_KEY_HEADER) or ""
    if not hmac.compare_digest(given.encode(), key.encode()):
        return _outcome_response(403, "forbidden", "Requests must come through the Endod API gateway.")
    return None


def _no_store(response: JSONResponse) -> JSONResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _log_request(caller: Caller, method: str, path: str, status: int, duration_ms: int, ip: str) -> None:
    with session_scope(caller.hospital_id) as session:
        session.add(IntegrationRequest(hospital_id=caller.hospital_id, client_pk=caller.client_pk,
                                       method=method[:8], path=path[:300], status=status,
                                       duration_ms=duration_ms, ip=ip[:64] if ip else None))


def _guide() -> str:
    """The guide, without its hidden blocks (``<!-- ... -->``: e.g. video visits while they are off)."""
    try:
        return re.sub(r"<!--.*?-->\n?", "", GUIDE.read_text(encoding="utf-8"), flags=re.S)
    except OSError:
        return "The guide is docs/integrations.md in the Hospital-service repository."


# --- reading back what a system sent ------------------------------------------------------------------

#: FHIR type -> the record kinds it becomes.
READ_BACK = {
    "Observation": (RecordCategory.LAB_RESULT,), "DiagnosticReport": (RecordCategory.LAB_RESULT, RecordCategory.IMAGING),
    "MedicationRequest": (RecordCategory.PRESCRIPTION,), "Condition": (RecordCategory.DIAGNOSIS,),
    "Encounter": (RecordCategory.VISIT_NOTE,), "DocumentReference": (RecordCategory.DOCUMENT,),
}
_CATEGORY_SCOPE = {RecordCategory.LAB_RESULT: S.LABS, RecordCategory.IMAGING: S.IMAGING,
                   RecordCategory.PRESCRIPTION: S.PRESCRIPTIONS, RecordCategory.DIAGNOSIS: S.DIAGNOSES,
                   RecordCategory.VISIT_NOTE: S.VISITS, RecordCategory.DOCUMENT: S.DOCUMENTS}
_STATUS = {"Observation": "final", "DiagnosticReport": "final", "MedicationRequest": "active",
           "Encounter": "finished", "DocumentReference": "current"}
PUBLISHED_EXTENSION = "https://endod-health.com/fhir/StructureDefinition/published-to-endod"


def sent_as(session, record: ClinicalRecord) -> Optional[str]:
    """The FHIR type a record was sent as through this API (the audit row of
    its creation names it); None for a record that came another way (the
    portal, a CSV import)."""
    detail = session.scalar(select(AuditEvent.detail).where(
        AuditEvent.hospital_id == record.hospital_id, AuditEvent.action == "integration_record_created",
        AuditEvent.target_id == record.patient_id,
        AuditEvent.detail.like(f'%"record_id": "{record.id}"%')).limit(1))
    try:
        return json.loads(detail).get("resource_type") if detail else None
    except ValueError:
        return None


def stored_resource(session, kind: str, record: ClinicalRecord, patient: Patient, hospital: Hospital,
                    own: Optional[IntegrationResource], client_id: str) -> Dict[str, Any]:
    """What Endod stored for a resource, as a FHIR resource of the type it was sent as."""
    when = ensure_aware(record.occurred_at).isoformat()
    out: Dict[str, Any] = {
        "resourceType": kind, "id": record.id,
        "meta": {"versionId": str(record.version), "lastUpdated": ensure_aware(record.updated_at).isoformat()},
        "subject": {"identifier": {"system": fhir.mrn_system(hospital), "value": patient.mrn}},
        "text": {"status": "generated",
                 "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">{html.escape(record.title)}</div>"},
        "extension": [{"url": PUBLISHED_EXTENSION, "valueBoolean": bool(record.published_dedan_id) and
                       record.published_version == record.version and not record.retracted}],
    }
    if own is not None:
        out["identifier"] = [{"system": f"https://endod-health.com/integrations/{client_id}/{kind}",
                              "value": own.resource_id}]
    if kind == "Condition":
        out["code"] = {"text": record.title}
        out["recordedDate"] = when
        out["verificationStatus"] = {"coding": [{"code": "entered-in-error" if record.retracted else "confirmed"}]}
    else:
        out["status"] = "entered-in-error" if record.retracted else _STATUS[kind]
    if kind in ("Observation", "DiagnosticReport"):
        out["code"] = {"text": record.title}
        out["effectiveDateTime"] = when
        if kind == "DiagnosticReport":
            out["category"] = [{"coding": [{"code": "RAD" if record.category == RecordCategory.IMAGING else "LAB"}]}]
    elif kind == "MedicationRequest":
        out["intent"] = "order"
        out["medicationCodeableConcept"] = {"text": record.title}
        out["authoredOn"] = when
    elif kind == "Encounter":
        out["type"] = [{"text": record.title}]
        out["period"] = {"start": when}
    elif kind == "DocumentReference":
        out["description"] = record.title
        out["date"] = when
        out["content"] = [{"attachment": {"contentType": f.content_type, "title": f.filename, "size": f.size,
                                          "hash": f.sha256}} for f in records.files_of(session, record.id)]
    return out


def create_app() -> FastAPI:  # noqa: C901 -- the app and its handlers in one place
    api = FastAPI(
        title="Endod Hospital Integration API", version="1.1.0", description=_guide(),
        docs_url=None, redoc_url=None, openapi_url="/openapi.json",
    )

    @api.middleware("http")
    async def request_log(request: Request, call_next):
        refused = edge_refusal(request)
        if refused is not None:
            return refused
        started = time.perf_counter()
        who = Caller()
        request.state.caller = who
        address = client_address(request)
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - started) * 1000)
        path = request.url.path
        # Never the body, the query string or a header: method, path, status, client, time, address.
        logger.info("integration_request method=%s path=%s status=%s client=%s ms=%s", request.method, path,
                    response.status_code, who.client_id or "-", duration_ms)
        if who.client_pk and who.hospital_id:
            try:
                await run_in_threadpool(_log_request, who, request.method, path, response.status_code,
                                        duration_ms, address)
            except Exception:  # noqa: BLE001 -- the answer stands even if the log row cannot be written
                logger.exception("integration_request_log_failed client=%s", who.client_id)
        return response

    @api.exception_handler(tokens.OAuthError)
    async def oauth_error(_request: Request, exc: tokens.OAuthError):
        return _no_store(JSONResponse(status_code=exc.status_code, headers=exc.headers,
                                      content={"error": exc.error, "error_description": exc.description}))

    @api.exception_handler(tokens.TokenRejected)
    async def token_rejected(_request: Request, exc: tokens.TokenRejected):
        return _outcome_response(exc.status_code, "security" if exc.status_code in (401, 403) else "throttled",
                                 exc.description, exc.headers)

    @api.exception_handler(fhir.FhirError)
    async def fhir_error(_request: Request, exc: fhir.FhirError):
        return _outcome_response(exc.status_code, exc.code, exc.message,
                                 body=fhir.error_outcome(exc.code, exc.message, exc.issues))

    @api.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        code = {404: "not-found", 409: "conflict", 400: "invalid", 403: "forbidden", 429: "throttled"}.get(
            exc.status_code, "processing")
        return _outcome_response(exc.status_code, code, message, getattr(exc, "headers", None))

    @api.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", [])[1:]) or "request"
        return _outcome_response(422, "invalid", f"{field}: {first.get('msg', 'invalid value')}")

    @api.exception_handler(Exception)
    async def unexpected(request: Request, _exc: Exception):
        logger.exception("integration_unhandled_error path=%s", request.url.path)
        return _outcome_response(500, "exception", "Internal server error.")

    # --- discovery -----------------------------------------------------------------------------

    @api.get("/.well-known/jwks.json", tags=[D.AUTH], summary="The keys that sign access tokens",
             response_model=None, openapi_extra={"security": []},
             responses={200: {"model": M.Jwks, "description": "A JSON Web Key Set (ES256). Cache it for 5 "
                                                             "minutes; a token's `kid` names its key."},
                        503: {"description": "The integration API is not available.",
                              "content": {FHIR_JSON: {"schema": D.OUTCOME_REF}}}})
    def jwks() -> JSONResponse:
        """No access token needed."""
        try:
            keys = signing.jwks()
        except signing.SigningKeyMissing:
            return _outcome_response(503, "transient", "The integration API is not available.")
        return JSONResponse(keys, headers={"Cache-Control": "public, max-age=300"})

    @api.get("/docs", include_in_schema=False)
    def docs() -> HTMLResponse:
        # Relative: right both here and behind nginx at the public URL.
        return get_swagger_ui_html(openapi_url="openapi.json", title="Endod Hospital Integration API")

    # --- the token endpoint ----------------------------------------------------------------------

    token_errors = {status: {"model": M.OAuthErrorBody, "description": when} for status, when in (
        (400, "`unsupported_grant_type`, `invalid_request`, `unauthorized_client` (hospital not approved or "
              "suspended) or `invalid_scope`."),
        (401, "`invalid_client`: unknown or disconnected client, wrong secret, bad assertion (signature, aud, exp, "
              "reused jti), or an address not allowed."),
        (413, "`invalid_request`: the token request is too large."),
        (429, "`slow_down`: too many token requests; wait `Retry-After` seconds."))}

    @api.post("/oauth/token", tags=[D.AUTH], summary="Get an access token (OAuth 2.0 client credentials)",
              response_model=None,
              responses={200: {"model": M.TokenResponse, "description": "An access token, valid 5 minutes."},
                         **token_errors},
              openapi_extra={"security": [], "requestBody": {"required": True, "content": {
                  "application/x-www-form-urlencoded": {
                      "schema": {"type": "object", "properties": {
                          "grant_type": {"type": "string", "enum": ["client_credentials"]},
                          "scope": {"type": "string", "description": "Space-separated; default: every granted "
                                                                     "scope. A scope not granted is refused."},
                          "client_id": {"type": "string", "description": "client_secret_post, or with an "
                                                                         "assertion."},
                          "client_secret": {"type": "string", "description": "client_secret_post (prefer HTTP "
                                                                             "Basic)."},
                          "client_assertion_type": {"type": "string", "enum": [tokens.ASSERTION_TYPE]},
                          "client_assertion": {"type": "string", "description": "private_key_jwt: a JWT signed "
                                                                                "ES256 or RS256 by your key; iss "
                                                                                "and sub your client ID, aud the "
                                                                                "token URL, exp at most 5 minutes "
                                                                                "ahead, a unique jti."}},
                          "required": ["grant_type"]},
                      "examples": {
                          "basic": {"summary": "Client secret in HTTP Basic (send -u CLIENT_ID:SECRET)",
                                    "value": {"grant_type": "client_credentials",
                                              "scope": "records.labs.write bookings.read"}},
                          "post": {"summary": "client_secret_post",
                                   "value": {"grant_type": "client_credentials", "client_id": "endod_live_3f9a...",
                                             "client_secret": "..."}},
                          "private_key_jwt": {"summary": "private_key_jwt (SMART Backend Services)", "value": {
                              "grant_type": "client_credentials", "scope": "records.labs.write",
                              "client_assertion_type": tokens.ASSERTION_TYPE,
                              "client_assertion": "eyJhbGciOiJFUzI1NiIsImtpZCI6Im15LWtleS0xIn0..."}}}}}}})
    async def token(request: Request) -> JSONResponse:
        """Authenticate with the client secret (HTTP Basic, or client_id and
        client_secret in the form) or a client assertion (private_key_jwt).
        Answers an access token valid 5 minutes. Errors are OAuth errors
        (`error`, `error_description`), not OperationOutcomes."""
        address = client_address(request)
        tokens.check_caller(address)
        if not (request.headers.get("content-type") or "").lower().startswith("application/x-www-form-urlencoded"):
            raise tokens.OAuthError("invalid_request", "Send the form as application/x-www-form-urlencoded.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_TOKEN_REQUEST:
                raise tokens.OAuthError("invalid_request", "The token request is too large.", 413)
        try:
            form = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=20)
        except (UnicodeDecodeError, ValueError):
            raise tokens.OAuthError("invalid_request", "The form could not be read.") from None
        result = await run_in_threadpool(tokens.issue, form, request.headers.get("authorization"), address,
                                         request.state.caller)
        return _no_store(JSONResponse(result))

    # --- records (FHIR) ---------------------------------------------------------------------------

    async def _write(request: Request, who: Caller, resource_type: Optional[str],
                     idempotency_key: Optional[str]) -> JSONResponse:
        if not any(s in who.scopes for s in RECORD_SCOPES):
            raise tokens.TokenRejected(403, "insufficient_scope", "This connection may not send records.")
        kind = (request.headers.get("content-type") or "").lower()
        if not (kind.startswith(FHIR_JSON) or kind.startswith("application/json")):
            raise fhir.FhirError(415, "not-supported", f"Send {FHIR_JSON}.")
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > fhir.MAX_BODY_BYTES:
            raise fhir.FhirError(413, "too-costly", "A request can be at most 10 MB.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > fhir.MAX_BODY_BYTES:
                raise fhir.FhirError(413, "too-costly", "A request can be at most 10 MB.")
        status, content, headers = await run_in_threadpool(
            fhir.handle, who, bytes(body), resource_type, idempotency_key, request.method, request.url.path)
        return JSONResponse(status_code=status, content=content, headers=headers, media_type=FHIR_JSON)

    idempotency = Header(default=None, alias="Idempotency-Key",
                         description="Your unique id for this request: the same key and request answer the first "
                                     "answer again for 24 hours (`Idempotent-Replayed: true`); the same key with "
                                     "another request is refused (422).")
    write_errors = D.errors(400, 401, 403, 409, 413, 415, 422, 429, examples={
        400: "Send a Bundle of type transaction or batch.", 409: "A resource cannot move to another patient or "
                                                                 "kind of record; send it with a new id.",
        422: "Unknown patient: SPH-404404. Patients are matched by the hospital number or the Endod ID and must "
             "already be registered at the hospital."})
    any_record = [{"endod": [s]} for s in RECORD_SCOPES]

    @api.post("/fhir", tags=[D.RECORDS], summary="Send a Bundle (transaction or batch)", response_model=None,
              description="At most 100 entries and 10 MB. A **transaction** is all or nothing (if any entry fails, "
                          "nothing is stored and the answer is an OperationOutcome naming each failed entry); a "
                          "**batch** handles each entry on its own (a failed entry has an error status and an "
                          "OperationOutcome in `response.outcome`). Each entry needs the scope of its resource "
                          "(see each resource's endpoint).\n\n**Scope:** any `records.*.write` (per entry).",
              responses={200: {"description": "A transaction-response or batch-response Bundle, one entry per "
                                               "entry sent, in order.",
                               "headers": D.IDEMPOTENT_REPLAY,
                               "content": {FHIR_JSON: {"schema": {"$ref": "#/components/schemas/FhirBundleResponse"},
                                                       "examples": F.BUNDLE_RESPONSE_EXAMPLES}}},
                         **write_errors},
              openapi_extra={"security": any_record, "requestBody": {"required": True, "content": {FHIR_JSON: {
                  "schema": {"$ref": "#/components/schemas/FhirBundle"}, "examples": F.BUNDLE_EXAMPLES}}}})
    async def post_bundle(request: Request, who: Caller = Depends(caller),
                          idempotency_key: Optional[str] = idempotency) -> JSONResponse:
        return await _write(request, who, None, idempotency_key)

    def _resource_route(kind: str) -> None:
        scopes = F.SCOPE_OF[kind]
        location = f"{kind}/5f0c1e2d3c4b5a69788796a5b4c3d2e1/_history/1"
        responses = {
            201: {"description": "Stored. `Location`: Type/<record id>/_history/<version> (read it back with "
                                 "GET /fhir/Type/<id>).",
                  "headers": {"Location": {"schema": {"type": "string"}, "example": location},
                              "ETag": {"schema": {"type": "string"}, "example": "W/\"1\""}, **D.IDEMPOTENT_REPLAY},
                  "content": {FHIR_JSON: {"schema": D.OUTCOME_REF, "examples": {
                      "stored": {"summary": "Stored", "value": F.outcome_example(
                          "informational", "Stored.", severity="information")},
                      "test_mode": {"summary": "Test connection: nothing stored", "value": F.outcome_example(
                          "informational", "Test mode: nothing was stored. This would store a record for the "
                                           "patient it names, if that patient is registered at the hospital.",
                          severity="information")}}}}},
            200: {"description": "A correction (a new version) or a repeat (nothing changed), with `Location`.",
                  "headers": {"Location": {"schema": {"type": "string"}}, "ETag": {"schema": {"type": "string"}}},
                  "content": {FHIR_JSON: {"schema": D.OUTCOME_REF, "example": F.outcome_example(
                      "informational", "Already stored; nothing changed.", severity="information")}}},
            **write_errors}
        needs_text = " or ".join(f"`{s}`" for s in scopes)

        async def post_one(request: Request, who: Caller = Depends(caller),
                           idempotency_key: Optional[str] = idempotency) -> JSONResponse:
            return await _write(request, who, kind, idempotency_key)

        post_one.__name__ = f"post_{kind}"
        api.post(f"/fhir/{kind}", tags=[D.RECORDS], summary=f"Send a {kind}", response_model=None,
                 description=f"{F.RESOURCES[kind]['description']}\n\nName the patient in `subject` by the "
                             "hospital number or the Endod ID. Give an `id` (and `meta.versionId`) to correct the "
                             f"record later by sending it again.\n\n**Scope:** {needs_text}.",
                 responses=responses,
                 openapi_extra={"security": [{"endod": [s]} for s in scopes], "requestBody": {
                     "required": True, "content": {FHIR_JSON: {"schema": {"$ref": f"#/components/schemas/Fhir{kind}"},
                                                               "examples": F.EXAMPLES[kind]}}}})(post_one)

    for kind in fhir.SUPPORTED:
        _resource_route(kind)

    @api.post("/fhir/{resource_type}", include_in_schema=False)
    async def post_other(resource_type: str, request: Request, who: Caller = Depends(caller)) -> JSONResponse:
        """Every type not accepted (each accepted one has its own route above)."""
        if resource_type == "Patient":
            raise fhir.FhirError(400, "not-supported", "Patients are not created through FHIR: register them with "
                                                       "POST /patients (Endod issues the hospital number).")
        raise fhir.FhirError(400, "not-supported", f"{resource_type[:40]} is not accepted; send one of "
                                                   f"{', '.join(fhir.SUPPORTED)}.")

    @api.get("/fhir/{resource_type}/{resource_id}", tags=[D.RECORDS], response_model=None,
             summary="Read back a resource you sent",
             description="What Endod stored for a resource this hospital's systems sent: by the record id of its "
                         "`Location` (Type/<id>/_history/n), or by your own resource id (this connection's). "
                         "`status` is `entered-in-error` once it was retracted at the hospital; the "
                         "published-to-endod extension says whether the patient's Endod app has this version. "
                         "A record is served only as the type it was sent as; records entered in the portal "
                         "or imported from a file are not served here.\n\nTest connections store nothing: "
                         "always 404.\n\n**Scope:** the write scope of the resource (e.g. `records.labs.write` "
                         "for an Observation).",
             responses={200: {"description": "The stored resource.", "content": {FHIR_JSON: {
                 "schema": {"$ref": "#/components/schemas/FhirStoredResource"}, "example": F.READ_BACK_EXAMPLE}}},
                 **D.errors(400, 401, 403, 404, 422, 429)},
             openapi_extra={"security": any_record})
    def read_resource(resource_type: str = PathParam(description="Observation, DiagnosticReport, "
                                                                 "MedicationRequest, Condition, Encounter or "
                                                                 "DocumentReference.",
                                                     json_schema_extra={"enum": list(fhir.SUPPORTED)}),
                      resource_id: str = PathParam(max_length=64), who: Caller = Depends(caller)) -> JSONResponse:
        if resource_type not in READ_BACK:
            raise fhir.FhirError(400, "not-supported", f"{resource_type[:40]} is not served; read one of "
                                                       f"{', '.join(fhir.SUPPORTED)}.")
        possible = {_CATEGORY_SCOPE[c] for c in READ_BACK[resource_type]}
        if not possible & set(who.scopes):
            wanted = sorted(possible)[0] if len(possible) == 1 else " or ".join(sorted(possible))
            raise tokens.TokenRejected(403, "insufficient_scope", f"This needs the scope {wanted}.",
                                       {"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{wanted}"'})
        if is_test(who):
            raise fhir.FhirError(404, "not-found", "Test connections store nothing: there is nothing to read back.")
        with session_scope(who.hospital_id) as session:
            own = session.scalar(select(IntegrationResource).where(
                IntegrationResource.client_pk == who.client_pk, IntegrationResource.resource_type == resource_type,
                IntegrationResource.resource_id == resource_id))
            record_id = own.record_id if own is not None else resource_id
            record = session.scalar(select(ClinicalRecord).where(
                ClinicalRecord.id == record_id, ClinicalRecord.hospital_id == who.hospital_id,
                ClinicalRecord.source == "import", ClinicalRecord.category.in_(READ_BACK[resource_type])))
            if record is None or sent_as(session, record) != resource_type:
                # Never served as another type than it was sent as (a lab Observation is no DiagnosticReport).
                raise fhir.FhirError(404, "not-found", f"{resource_type}/{resource_id[:64]} not found.")
            if _CATEGORY_SCOPE[record.category] not in who.scopes:
                tokens.require(who, _CATEGORY_SCOPE[record.category])
            if own is None:
                own = session.scalar(select(IntegrationResource).where(
                    IntegrationResource.client_pk == who.client_pk, IntegrationResource.record_id == record.id))
            patient = session.get(Patient, record.patient_id)
            hospital = session.get(Hospital, who.hospital_id)
            body = stored_resource(session, resource_type, record, patient, hospital, own, who.client_id)
            audit(session, who.hospital_id, None, "patient_records_viewed", "patient", patient.id,
                  {"record_id": record.id, **via(who)})
            return JSONResponse(body, media_type=FHIR_JSON,
                                headers={"ETag": f'W/"{record.version}"'})

    # --- the patient journey ------------------------------------------------------------------------

    journey.add_routes(api)

    # --- the price list ----------------------------------------------------------------------------------

    pricing.add_routes(api)

    # --- charges: hospital services with Endod's service fee ----------------------------------------------

    charges.add_routes(api)

    # --- webhooks (documented only: Endod sends them) -------------------------------------------------

    _webhook_docs(api)

    def openapi() -> Dict[str, Any]:
        if api.openapi_schema:
            return api.openapi_schema
        schema = get_openapi(title=api.title, version=api.version, openapi_version="3.1.0",
                             summary="Hospitals keep their own system and use Endod as a layer.",
                             description=_overview() + "\n\n---\n\n" + api.description, routes=api.routes,
                             webhooks=api.webhooks.routes, tags=D.tags(journey.video_visits()),
                             servers=[{"url": tokens.public_url()}])
        components = schema.setdefault("components", {})
        schemas = components.setdefault("schemas", {})
        schemas.update(F.components())
        outcome = M.OperationOutcome.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(outcome.pop("$defs", {}))
        schemas["OperationOutcome"] = outcome
        # FastAPI's validation-error schemas are never answered (errors are OperationOutcomes).
        for name in ("HTTPValidationError", "ValidationError"):
            schemas.pop(name, None)
        _replace_validation_errors(schema)
        components["securitySchemes"] = {"endod": {
            "type": "oauth2",
            "description": "OAuth 2.0 client credentials. Authenticate at the token URL with the client secret "
                           "(HTTP Basic `client_secret_basic`, or `client_secret_post`) or with a signed client "
                           "assertion (`private_key_jwt`, SMART Backend Services: a JWT signed ES256 or RS256 by "
                           "your key, whose public JWKS you paste in the portal; iss and sub your client ID, aud "
                           "the token URL, exp at most 5 minutes ahead, a unique jti). Access tokens are JWTs "
                           "signed ES256 (keys at /.well-known/jwks.json), valid 5 minutes. Each operation names "
                           "the scope it needs.",
            "flows": {"clientCredentials": {"tokenUrl": tokens.token_url(), "scopes": {
                name: f"{label}: {description}" for name, (label, description) in S.SCOPES.items()}}}}}
        schema["security"] = [{"endod": []}]
        schema["externalDocs"] = {"description": "The integration guide (the same text as this description)",
                                  "url": GUIDE_URL}
        api.openapi_schema = schema
        return schema

    api.openapi = openapi
    return api


def _replace_validation_errors(schema: Dict[str, Any]) -> None:
    """Every 422 is an OperationOutcome (FastAPI documents its own validation error shape)."""
    for item in schema.get("paths", {}).values():
        for operation in item.values():
            response = operation.get("responses", {}).get("422")
            if response is None:
                continue
            content = response.get("content", {})
            if "application/json" in content and "HTTPValidationError" in str(content["application/json"]):
                operation["responses"]["422"] = D.errors(422)[422]


def _overview() -> str:
    lines = [
        "**Hospitals keep their own EMR and use Endod as a layer.** Everything the Endod hospital portal does in "
        "the patient journey can be done through this API:",
        "",
        "1. **Patients**: register a patient (Endod issues the hospital number, MRN), read them, link them to "
        "their Endod account (or unlink): `POST /patients`, `GET /patients/{mrn}`, `POST|DELETE "
        "/patients/{mrn}/link`.",
        ("2. **Bookings** patients make in the Endod app: read, approve or decline video visits, cancel, complete: "
         "`/bookings`." if journey.video_visits() else
         "2. **Bookings** patients make in the Endod app (in-person visits): read, cancel, complete: `/bookings`."),
        "3. **Queue**: check in, call the next patient, done, skip, cancel: `/queue`.",
        "4. **Records**: send lab results, imaging reports, prescriptions, diagnoses, visit notes and documents as "
        "FHIR R4 (`POST /fhir/{Type}` or a Bundle at `POST /fhir`), and read them back.",
        "5. **Follow-ups**: set and cancel follow-up dates (the patient gets an SMS and a reminder).",
        "6. **Prescriptions**: see what pharmacies gave (`GET /prescriptions/{id}`).",
        "7. **Prices**: keep the hospital's price list in step with your system: the in-person consultation price "
        "patients see, lab tests, imaging and procedures (`PUT /prices/...`, `GET /prices`).",
        "8. **Webhooks**: Endod tells your system when bookings, patient links and dispensing change (see "
        "`webhooks` below), signed with `Endod-Signature`.",
        "",
        "Get an access token at `/oauth/token` (client credentials) with the scopes of the operations you call; "
        "each operation lists its scope. Errors are FHIR OperationOutcomes. Test connections (`endod_test_...`) "
        "check everything and answer made-up data, storing nothing.",
        "",
        f"The full guide follows; it is also at {GUIDE_URL}.",
    ]
    return "\n".join(lines)


SIGNATURE_DOC = (
    "Every event is POSTed as JSON with the header `Endod-Signature: t=<unix time>,v1=<hex>`, where `<hex>` is "
    "the HMAC-SHA256 of `\"<t>.<raw body>\"` under your webhook secret (`whsec_...`, shown once in the portal). "
    "Compare in constant time, against the raw body, and refuse events older than 5 minutes. Also sent: "
    "`Endod-Event-Id`, `Endod-Event-Type`, `User-Agent: Endod-Webhooks/1`.\n\n"
    "Answer any **2xx** within 10 seconds. Anything else, a timeout or a redirect (never followed) is retried "
    "after 1 min, 5 min, 15 min, 30 min, 1 h, 2 h, 4 h, then every 6 h, for up to **24 hours**; then the event "
    "is dropped. Events can arrive more than once and out of order: skip repeats by `id`. Live connections with "
    "the `webhooks` scope and a webhook URL get every event; Test connections get only `endpoint.test`.")


def _webhook_docs(api: FastAPI) -> None:
    """Every event, as an OpenAPI 3.1 webhook: its payload, an example, the signature."""
    for event, (model, when, example) in M.WEBHOOK_EVENTS.items():
        if event != webhooks.TEST_EVENT:
            assert event in webhooks.EVENTS, event

        def receiver(body: model, endod_signature: str = Header(  # type: ignore[valid-type]
                alias="Endod-Signature", description="t=<unix time>,v1=<hex HMAC-SHA256 of \"<t>.<raw body>\">",
                examples=["t=1759298400,v1=5257a869e7ecebeda32affa62cdca3fa51cad7e77a0e56ff536d0ce8e108d8bd"]),
                endod_event_id: str = Header(alias="Endod-Event-Id"),
                endod_event_type: str = Header(alias="Endod-Event-Type")) -> None:
            """Documented only."""

        # Set here: the annotation names the loop's model (annotations are strings in this module).
        receiver.__annotations__["body"] = model
        receiver.__name__ = f"webhook_{event.replace('.', '_')}"
        api.webhooks.post(
            event, tags=[D.WEBHOOKS], summary=f"{event}: {when}", description=f"{when}\n\n{SIGNATURE_DOC}",
            response_model=None, status_code=204,
            responses={204: {"description": "Any 2xx: received."},
                       400: {"description": "Anything else (or a timeout) is retried with backoff."}},
            openapi_extra={"requestBody": {"required": True, "content": {"application/json": {
                "schema": {"$ref": f"#/components/schemas/{model.__name__}"},
                "example": copy.deepcopy(example)}}}})(receiver)
