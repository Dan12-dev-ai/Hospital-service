"""What every call of the integration API shares: the caller's address and
access token, OperationOutcome answers, and Idempotency-Key handling for
the JSON endpoints (the FHIR endpoints have theirs in :mod:`.fhir`)."""

from __future__ import annotations

import ipaddress
import json
from typing import Any, Callable, Dict, Optional, Tuple

from fastapi import Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.db import session_scope
from app.integrations import fhir, tokens
from app.integrations.tokens import Caller
from app.models import IntegrationIdempotency, IntegrationMode

FHIR_JSON = "application/fhir+json"
CLIENT_IP_HEADER = "x-endod-client-ip"


def client_address(request: Request) -> str:
    """The caller's address as nginx saw it (X-Endod-Client-IP), else the peer's.
    Never X-Forwarded-For (a client could choose it)."""
    value = (request.headers.get(CLIENT_IP_HEADER) or "").strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return request.client.host if request.client else "unknown"


def caller(request: Request, authorization: Optional[str] = Header(default=None, include_in_schema=False)) -> Caller:
    """The client behind the access token (checked again in the database, its
    address allow-list, the hospital's approval and the rate limit)."""
    return tokens.authenticate(authorization, client_address(request), request.state.caller)


def outcome_response(status_code: int, code: str, message: str, headers: Optional[Dict[str, str]] = None,
                     body: Optional[Dict[str, Any]] = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=body or fhir.outcome("error", code, message),
                        headers=headers, media_type=FHIR_JSON)


def require_any(who: Caller, *scopes: str) -> None:
    """403 insufficient_scope unless the token carries one of ``scopes``."""
    if not any(s in who.scopes for s in scopes):
        wanted = " ".join(scopes)
        raise tokens.TokenRejected(403, "insufficient_scope", f"This needs one of the scopes {wanted}.",
                                   {"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{wanted}"'})


def is_test(who: Caller) -> bool:
    return who.mode == IntegrationMode.TEST


Work = Callable[[Any], Tuple[int, Dict[str, Any]]]


def _run(who: Caller, method: str, path: str, raw: bytes, key: Optional[str], work: Work,
         conflict: str) -> JSONResponse:
    if key is not None and not 0 < len(key) <= fhir.MAX_IDEMPOTENCY_KEY:
        raise fhir.FhirError(400, "value", f"The Idempotency-Key must be 1 to {fhir.MAX_IDEMPOTENCY_KEY} characters.")
    fingerprint = fhir.request_hash(method, path, raw)
    try:
        with session_scope(who.hospital_id) as session:
            if key is not None:
                replayed = fhir.replay(session, who, key, fingerprint)
                if replayed is not None:
                    return JSONResponse(status_code=replayed[0], content=replayed[1],
                                        headers={"Idempotent-Replayed": "true"})
            status, content = work(session)
            if key is not None:
                # In the same transaction as the change: the answer is remembered only if the change is saved.
                session.add(IntegrationIdempotency(
                    hospital_id=who.hospital_id, client_pk=who.client_pk, key=key, request_hash=fingerprint,
                    status_code=status, response=json.dumps(content)))
                session.flush()
            return JSONResponse(status_code=status, content=content)
    except IntegrityError:
        raise fhir.FhirError(409, "conflict", conflict) from None


async def run(request: Request, who: Caller, key: Optional[str], work: Work,
              conflict: str = "The same request was being processed at the same time; send it again.") \
        -> JSONResponse:
    """Do ``work(session)`` -> (status, body) in one transaction of the caller's
    hospital (row-level security). With an Idempotency-Key: the same key and
    request answer the first answer again for a day (``Idempotent-Replayed``),
    the same key with another request is refused (422). Errors (HTTPException,
    FhirError) roll everything back and are never remembered."""
    raw = await request.body()
    return await run_in_threadpool(_run, who, request.method, request.url.path, raw, key, work, conflict)


def needs(*scopes: str):
    """A dependency: the caller, refused (403 insufficient_scope) unless the
    token carries one of ``scopes``. Runs before the body is read or checked."""
    def dependency(request: Request,
                   authorization: Optional[str] = Header(default=None, include_in_schema=False)) -> Caller:
        who = caller(request, authorization)
        if len(scopes) == 1:
            tokens.require(who, scopes[0])
        else:
            require_any(who, *scopes)
        return who
    return dependency


def via(who: Caller) -> Dict[str, Any]:
    """What the audit log says about an integration's change (never a secret)."""
    return {"client_id": who.client_id, "via": "integration"}
