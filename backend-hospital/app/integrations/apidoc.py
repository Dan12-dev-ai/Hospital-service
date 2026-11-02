"""Helpers that document operations in the OpenAPI document: their scope
(``security``), their answers (success with a schema and an example, every
error as an OperationOutcome with an example) and their tags."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Type

from pydantic import BaseModel

FHIR_JSON = "application/fhir+json"
OUTCOME_REF = {"$ref": "#/components/schemas/OperationOutcome"}

# Tags, in the order Swagger shows them.
AUTH = "Authentication"
RECORDS = "Records (FHIR)"
PATIENTS = "Patients"
BOOKINGS = "Bookings"
DOCTORS = "Doctors"
FOLLOW_UPS = "Follow-ups"
PRESCRIPTIONS = "Prescriptions"
QUEUE = "Queue"
WEBHOOKS = "Webhooks"

TAGS = [
    {"name": AUTH, "description": "OAuth 2.0 client credentials (client secret or private_key_jwt) and the keys "
                                  "that sign access tokens."},
    {"name": RECORDS, "description": "Send clinical records as FHIR R4 resources (one, or a Bundle) and read back "
                                     "what Endod stored. Records are filed for patients registered at the hospital."},
    {"name": PATIENTS, "description": "Register patients (Endod issues the hospital number), read them, and link "
                                      "them to their Endod account (or unlink)."},
    {"name": BOOKINGS, "description": "Bookings patients make through Endod: read them, approve or decline video "
                                      "visits, cancel, complete."},
    {"name": DOCTORS, "description": "The hospital's doctors, to name one when approving a visit, checking a "
                                     "patient in or setting a follow-up."},
    {"name": FOLLOW_UPS, "description": "Follow-up dates: the patient gets an SMS and a reminder."},
    {"name": PRESCRIPTIONS, "description": "What pharmacies gave from the hospital's prescriptions."},
    {"name": QUEUE, "description": "Doctors' queues for the day: check in, call the next patient, done, skip, "
                                   "cancel."},
    {"name": WEBHOOKS, "description": "Events Endod POSTs to your webhook URL (see `webhooks` in this document), "
                                      "signed with `Endod-Signature`."},
]

#: status -> (when, issue code, example message)
ERRORS: Dict[int, tuple] = {
    400: ("A malformed request, an unsupported type, or a value not allowed.", "invalid",
          "status must be one of ['awaiting_doctor', 'confirmed', 'rejected', 'cancelled', 'completed']."),
    401: ("No access token, an invalid or expired one, a disconnected client, or credentials changed since it was "
          "issued (`WWW-Authenticate: Bearer error=\"invalid_token\"`).", "security", "The access token has expired."),
    403: ("A scope not granted (`insufficient_scope`), a call from an address not allowed, or a hospital not "
          "approved or suspended.", "security", "This needs the scope bookings.write."),
    404: ("Not found (another hospital's data is never visible).", "not-found", "Patient not found."),
    409: ("The change conflicts with the current state (e.g. a visit already closed), or the same request was "
          "processed at the same moment (send it again).", "processing", "This visit is already closed."),
    413: ("More than 100 entries, or more than 10 MB.", "too-costly", "A request can be at most 10 MB."),
    415: ("Not application/fhir+json (or application/json).", "not-supported", "Send application/fhir+json."),
    422: ("A value that cannot be used, or an Idempotency-Key reused for another request.", "invalid",
          "reason: String should have at least 2 characters"),
    429: ("Too many requests: wait `Retry-After` seconds (60 a minute per connection).", "throttled",
          "Too many requests for this client; try again shortly."),
}
#: What every call with an access token can answer.
AUTHENTICATED = (401, 403, 429)


def errors(*codes: int, examples: Optional[Dict[int, str]] = None) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for code in sorted(set(codes)):
        when, issue, message = ERRORS[code]
        message = (examples or {}).get(code, message)
        content: Dict[str, Any] = {"schema": OUTCOME_REF, "example": {
            "resourceType": "OperationOutcome", "issue": [{"severity": "error", "code": issue,
                                                           "diagnostics": message}]}}
        response: Dict[str, Any] = {"description": when, "content": {FHIR_JSON: content}}
        if code == 429:
            response["headers"] = {"Retry-After": {"description": "Seconds to wait.", "schema": {"type": "integer"}}}
        if code == 401:
            response["headers"] = {"WWW-Authenticate": {"schema": {"type": "string"}}}
        out[code] = response
    return out


def ok(status: int, model: Type[BaseModel], description: str, example: Any = None,
       headers: Optional[Dict[str, Any]] = None) -> Dict[int, Dict[str, Any]]:
    response: Dict[str, Any] = {"model": model, "description": description}
    if example is not None:
        response["content"] = {"application/json": {"example": example}}
    if headers:
        response["headers"] = headers
    return {status: response}


IDEMPOTENT_REPLAY = {"Idempotent-Replayed": {"description": "`true` when this is the stored answer to an "
                                                            "Idempotency-Key sent before.",
                                             "schema": {"type": "string", "enum": ["true"]}}}


def operation(scopes: Iterable[str], summary: str, description: str, success: Dict[int, Dict[str, Any]],
              error_codes: Iterable[int] = (), error_examples: Optional[Dict[int, str]] = None,
              tags: Optional[List[str]] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Keyword arguments for a route decorator. ``scopes``: any one of them is
    enough (each is listed as an alternative in ``security``)."""
    scopes = list(scopes)
    security = [{"endod": [s]} for s in scopes] if scopes else []
    responses = {**success, **errors(*AUTHENTICATED, 422, *error_codes, examples=error_examples)}
    needs = " or ".join(f"`{s}`" for s in scopes)
    text = f"{description}\n\n**Scope:** {needs}." if scopes else description
    return {"summary": summary, "description": text, "responses": responses, "tags": tags or [],
            "openapi_extra": {"security": security, **(extra or {})}, "response_model": None}
