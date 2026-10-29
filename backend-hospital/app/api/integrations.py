"""The integration API, served under /integrations/v1 (published by nginx at
HOSPITAL_INTEGRATIONS_PUBLIC_URL, e.g. https://api.endod-health.com/hospital/v1).

A FastAPI application of its own, run by its own service (the
``integrations`` service, app/integrations_main.py: the only one on the
shared edge network, and the only one with the token signing key), so it has its own
OpenAPI document (``/openapi.json``), its own docs page (``/docs``, with the
guide, docs/integrations.md) and its own errors: OAuth errors from the token
endpoint, FHIR OperationOutcomes everywhere else. Every call is written to the
request log (method, path, status, client, time, duration, address; never a
body), once the client is known.

Only nginx reaches it: every request must carry ``X-Endod-Edge-Key`` (the
shared EDGE_SHARED_SECRET, compared in constant time; without one configured,
production answers 503). The caller's address is taken ONLY from
``X-Endod-Client-IP``, which nginx sets; X-Forwarded-For is ignored.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import AwareDatetime
from sqlalchemy import select
from starlette.exceptions import HTTPException

from app.config import get_settings
from app.db import ensure_aware, session_scope
from app.integrations import fhir, scopes as S, signing, tokens
from app.integrations.tokens import Caller
from app.models import Booking, BookingStatus, IntegrationMode, IntegrationRequest

logger = logging.getLogger("hospital.integrations")

PREFIX = "/integrations/v1"
MAX_TOKEN_REQUEST = 16 * 1024
FHIR_JSON = "application/fhir+json"
GUIDE = Path(__file__).resolve().parents[1] / "integrations" / "guide.md"
RECORD_SCOPES = (S.LABS, S.PRESCRIPTIONS, S.DIAGNOSES, S.VISITS, S.DOCUMENTS, S.IMAGING)


EDGE_KEY_HEADER = "x-endod-edge-key"
CLIENT_IP_HEADER = "x-endod-client-ip"


def client_address(request: Request) -> str:
    """The caller's address as nginx saw it (X-Endod-Client-IP), else the peer's.
    Never X-Forwarded-For (a client could choose it)."""
    value = (request.headers.get(CLIENT_IP_HEADER) or "").strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return request.client.host if request.client else "unknown"


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


def _outcome_response(status_code: int, code: str, message: str, headers: Optional[Dict[str, str]] = None,
                      body: Optional[Dict[str, Any]] = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=body or fhir.outcome("error", code, message),
                        headers=headers, media_type=FHIR_JSON)


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
    try:
        return GUIDE.read_text(encoding="utf-8")
    except OSError:
        return "The guide is docs/integrations.md in the Hospital-service repository."


def create_app() -> FastAPI:
    api = FastAPI(
        title="Endod Hospital Integration API", version="1.0.0", description=_guide(),
        docs_url=None, redoc_url=None, openapi_url="/openapi.json",
    )

    @api.middleware("http")
    async def request_log(request: Request, call_next):
        refused = edge_refusal(request)
        if refused is not None:
            return refused
        started = time.perf_counter()
        caller = Caller()
        request.state.caller = caller
        address = client_address(request)
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - started) * 1000)
        path = request.url.path
        # Never the body, the query string or a header: method, path, status, client, time, address.
        logger.info("integration_request method=%s path=%s status=%s client=%s ms=%s", request.method, path,
                    response.status_code, caller.client_id or "-", duration_ms)
        if caller.client_pk and caller.hospital_id:
            try:
                await run_in_threadpool(_log_request, caller, request.method, path, response.status_code,
                                        duration_ms, address)
            except Exception:  # noqa: BLE001 -- the answer stands even if the log row cannot be written
                logger.exception("integration_request_log_failed client=%s", caller.client_id)
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
        return _outcome_response(exc.status_code, "not-found" if exc.status_code == 404 else "processing", message,
                                 getattr(exc, "headers", None))

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

    @api.get("/.well-known/jwks.json", tags=["auth"], summary="The keys that sign access tokens")
    def jwks() -> JSONResponse:
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

    @api.post("/oauth/token", tags=["auth"], summary="Get an access token (OAuth 2.0 client credentials)",
              openapi_extra={"security": [], "requestBody": {"required": True, "content": {
                  "application/x-www-form-urlencoded": {"schema": {"type": "object", "properties": {
                      "grant_type": {"type": "string", "enum": ["client_credentials"]},
                      "scope": {"type": "string", "description": "Space-separated; default: every granted scope."},
                      "client_id": {"type": "string"}, "client_secret": {"type": "string"},
                      "client_assertion_type": {"type": "string", "enum": [tokens.ASSERTION_TYPE]},
                      "client_assertion": {"type": "string"}}, "required": ["grant_type"]}}}}})
    async def token(request: Request) -> JSONResponse:
        """Authenticate with the client secret (HTTP Basic, or client_id and
        client_secret in the form) or a client assertion (private_key_jwt).
        Answers an access token valid 5 minutes."""
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

    # --- calls with an access token --------------------------------------------------------------

    def caller(request: Request, authorization: Optional[str] = Header(default=None, include_in_schema=False)) \
            -> Caller:
        return tokens.authenticate(authorization, client_address(request), request.state.caller)

    def booking_payload(b: Booking) -> Dict[str, Any]:
        return {
            "id": b.id, "endod_appointment_id": b.external_id, "status": b.status, "visit_mode": b.visit_mode,
            "service": b.service, "scheduled_at": ensure_aware(b.scheduled_at).isoformat(),
            "duration_minutes": b.duration_minutes,
            "patient": {"endod_id": b.patient_dedan_id, "name": b.patient_name, "phone": b.patient_phone},
            "reason": b.reason, "created_at": ensure_aware(b.created_at).isoformat(),
            "updated_at": ensure_aware(b.updated_at).isoformat(),
        }

    def sample_bookings() -> list:
        """What a Test connection sees: made-up bookings (never a real patient's)."""
        from datetime import datetime, time as clock, timedelta, timezone

        base = datetime.combine(datetime.now(timezone.utc).date() + timedelta(days=1), clock(6, 0), timezone.utc)
        rows = []
        for n, (mode, status) in enumerate((("in_person", "confirmed"), ("video", "awaiting_doctor"),
                                            ("in_person", "cancelled"))):
            at = (base + timedelta(hours=n)).isoformat()
            rows.append({
                "id": f"sample{n + 1:0>26}", "endod_appointment_id": f"sample-appointment-{n + 1}",
                "status": status, "visit_mode": mode, "service": "general_medicine", "scheduled_at": at,
                "duration_minutes": 30,
                "patient": {"endod_id": f"DE00000{n + 1}", "name": f"Sample Patient {n + 1}", "phone": None},
                "reason": "Cancelled by the patient." if status == "cancelled" else None,
                "created_at": base.isoformat(), "updated_at": base.isoformat(), "sample": True,
            })
        return rows

    @api.get("/bookings", tags=["bookings"], summary="Bookings patients made through Endod (bookings.read)")
    def list_bookings(status: Optional[str] = Query(default=None, description=f"One of {list(BookingStatus.ALL)}"),
                      scheduled_from: Optional[AwareDatetime] = Query(default=None, alias="from"),
                      scheduled_to: Optional[AwareDatetime] = Query(default=None, alias="to"),
                      updated_since: Optional[AwareDatetime] = None,
                      limit: int = Query(default=100, ge=1, le=500),
                      who: Caller = Depends(caller)) -> Dict[str, Any]:
        """Newest scheduled time last. Notes the patient typed are never included."""
        tokens.require(who, S.BOOKINGS_READ)
        if status is not None and status not in BookingStatus.ALL:
            raise HTTPException(status_code=400, detail=f"status must be one of {list(BookingStatus.ALL)}.")
        if who.mode == IntegrationMode.TEST:
            # Test connections never see real patients' bookings.
            return {"items": [b for b in sample_bookings() if status is None or b["status"] == status][:limit]}
        with session_scope(who.hospital_id) as session:
            query = select(Booking).where(Booking.hospital_id == who.hospital_id)
            if status:
                query = query.where(Booking.status == status)
            if scheduled_from:
                query = query.where(Booking.scheduled_at >= scheduled_from)
            if scheduled_to:
                query = query.where(Booking.scheduled_at < scheduled_to)
            if updated_since:
                query = query.where(Booking.updated_at >= updated_since)
            rows = session.scalars(query.order_by(Booking.scheduled_at, Booking.id).limit(limit))
            return {"items": [booking_payload(b) for b in rows]}

    @api.get("/bookings/{booking_id}", tags=["bookings"], summary="One booking (bookings.read)")
    def read_booking(booking_id: str, who: Caller = Depends(caller)) -> Dict[str, Any]:
        tokens.require(who, S.BOOKINGS_READ)
        if who.mode == IntegrationMode.TEST:
            found = next((b for b in sample_bookings() if b["id"] == booking_id), None)
            if found is None:
                raise HTTPException(status_code=404, detail="Booking not found.")
            return found
        with session_scope(who.hospital_id) as session:
            booking = session.scalar(select(Booking).where(Booking.id == booking_id,
                                                           Booking.hospital_id == who.hospital_id))
            if booking is None:
                raise HTTPException(status_code=404, detail="Booking not found.")
            return booking_payload(booking)

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

    write_doc = {"requestBody": {"required": True, "content": {FHIR_JSON: {"schema": {"type": "object"}}}}}

    @api.post("/fhir", tags=["fhir"], summary="Send a Bundle (transaction or batch)", openapi_extra=write_doc)
    async def post_bundle(request: Request, who: Caller = Depends(caller),
                          idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")) \
            -> JSONResponse:
        """At most 100 entries and 10 MB. A transaction is all or nothing; a
        batch handles each entry on its own. Answers a transaction-response or
        batch-response Bundle, or an OperationOutcome."""
        return await _write(request, who, None, idempotency_key)

    @api.post("/fhir/{resource_type}", tags=["fhir"], summary="Send one resource", openapi_extra=write_doc)
    async def post_resource(resource_type: str, request: Request, who: Caller = Depends(caller),
                            idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")) \
            -> JSONResponse:
        """Observation, DiagnosticReport, MedicationRequest, Condition, Encounter
        or DocumentReference. Answers 201 (or 200 for a correction or a repeat)
        with Location, or an OperationOutcome."""
        if resource_type not in fhir.SUPPORTED:
            raise fhir.FhirError(400, "not-supported", f"{resource_type[:40]} is not accepted; send one of "
                                                       f"{', '.join(fhir.SUPPORTED)}.")
        return await _write(request, who, resource_type, idempotency_key)

    def openapi() -> Dict[str, Any]:
        if api.openapi_schema:
            return api.openapi_schema
        schema = get_openapi(title=api.title, version=api.version, description=api.description, routes=api.routes,
                             servers=[{"url": tokens.public_url()}])
        schema.setdefault("components", {})["securitySchemes"] = {"endod": {
            "type": "oauth2", "description": "Client credentials: a client secret or a signed client assertion "
                                             "(private_key_jwt, SMART Backend Services).",
            "flows": {"clientCredentials": {"tokenUrl": tokens.token_url(), "scopes": {
                name: label for name, (label, _d) in S.SCOPES.items()}}}}}
        schema["security"] = [{"endod": []}]
        api.openapi_schema = schema
        return schema

    api.openapi = openapi
    return api
