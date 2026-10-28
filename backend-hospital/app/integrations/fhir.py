"""FHIR writes from a hospital's own system: a Bundle (transaction or batch)
or one resource, mapped to clinical records by the import's mapping code
(app/imports.py), never a copy of it.

* Patients are found by the hospital number (an identifier of the hospital's
  MRN system, :func:`mrn_system`) or the Endod ID
  (``https://endod-health.com/id``), among this hospital's patients only.
  They are never created, never matched by name. An unknown patient is an
  error for that entry (an OperationOutcome).
* A resource with an ``id`` is remembered (integration_resources): sent again
  with another ``meta.versionId`` (or other content), it corrects its record
  (a new version, published again like a correction in the portal); the same
  version again changes nothing. Without an ``id``, the same content twice
  is one record. An ``Idempotency-Key`` replays the first answer for a day.
* Every write goes through the ORM (encrypted at rest, app/sealing.py) in a
  transaction of the client's hospital (row-level security), is published to
  Endod for linked patients only (app/records.publish), and is audited with
  the client, the action and the record ids, never a clinical value.
* Test mode checks and maps everything and says what WOULD be stored; it
  stores nothing.
* A transaction is all or nothing; a batch handles each entry on its own.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import crypto, files, imports, records
from app.auth import audit
from app.db import new_id, session_scope, utcnow
from app.integrations import scopes as S
from app.integrations.tokens import Caller
from app.models import (
    ClinicalRecord, Hospital, IntegrationIdempotency, IntegrationMode, IntegrationResource, Patient, RecordFile,
)

MAX_ENTRIES = 100
MAX_BODY_BYTES = 10 * 1024 * 1024
#: How long an Idempotency-Key's answer is kept.
IDEMPOTENCY_FOR = timedelta(hours=24)
MAX_IDEMPOTENCY_KEY = 255
#: FHIR's id: letters, digits, "-" and ".", at most 64.
_FHIR_ID = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")

SUPPORTED = tuple(imports.API_MAPPERS)


def mrn_system(hospital: Hospital) -> str:
    """The identifier system of this hospital's numbers (MRNs), e.g.
    ``https://endod-health.com/hospital/sph/mrn``."""
    return f"https://endod-health.com/hospital/{hospital.code.lower()}/mrn"


class FhirError(Exception):
    """The whole request is refused (an OperationOutcome with this status)."""

    def __init__(self, status_code: int, code: str, message: str, issues: Optional[List[Dict[str, Any]]] = None):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message
        self.issues = issues


def outcome(severity: str, code: str, diagnostics: str, expression: Optional[str] = None) -> Dict[str, Any]:
    issue: Dict[str, Any] = {"severity": severity, "code": code, "diagnostics": diagnostics[:500]}
    if expression:
        issue["expression"] = [expression]
    return {"resourceType": "OperationOutcome", "issue": [issue]}


def error_outcome(code: str, message: str, issues: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    if issues:
        return {"resourceType": "OperationOutcome", "issue": issues}
    return outcome("error", code, message)


_STATUS_TEXT = {200: "200 OK", 201: "201 Created", 400: "400 Bad Request", 403: "403 Forbidden",
                409: "409 Conflict", 422: "422 Unprocessable Entity"}


class EntryFailed(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class EntryResult:
    status: int
    location: Optional[str] = None
    etag: Optional[str] = None
    outcome: Optional[Dict[str, Any]] = None

    def response(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"status": _STATUS_TEXT.get(self.status, str(self.status))}
        if self.location:
            out["location"] = self.location
        if self.etag:
            out["etag"] = self.etag
        if self.outcome:
            out["outcome"] = self.outcome
        return out


def scope_for(resource: Dict[str, Any]) -> str:
    """The scope a resource needs. Raises EntryFailed for anything not accepted."""
    kind = resource.get("resourceType")
    if kind == "Observation":
        return S.LABS
    if kind == "DiagnosticReport":
        if imports._category_has(resource, *imports.LAB_REPORT_CODES):
            return S.LABS
        if imports._category_has(resource, *imports.IMAGING_REPORT_CODES):
            return S.IMAGING
        raise EntryFailed(422, "invalid", "A DiagnosticReport must be a laboratory (LAB) or imaging (RAD) report.")
    scope = {"MedicationRequest": S.PRESCRIPTIONS, "Condition": S.DIAGNOSES, "Encounter": S.VISITS,
             "DocumentReference": S.DOCUMENTS}.get(kind)
    if scope is None:
        raise EntryFailed(400, "not-supported", f"{str(kind)[:40]} is not accepted; send one of "
                                                f"{', '.join(SUPPORTED)} (and Patient, to name the patient).")
    return scope


@dataclass
class Work:
    """One request being handled."""

    caller: Caller
    test: bool
    stored_files: List[str] = field(default_factory=list)


def _location(kind: str, record: ClinicalRecord) -> str:
    return f"{kind}/{record.id}/_history/{record.version}"


def _audit(session, caller: Caller, action: str, patient: Patient, record: ClinicalRecord, kind: str) -> None:
    # The client, the action and ids only: never a clinical value.
    audit(session, caller.hospital_id, None, action, "patient", patient.id,
          {"client_id": caller.client_id, "record_id": record.id, "resource_type": kind, "version": record.version})


def _store_document(session, work: Work, record: ClinicalRecord, patient: Patient,
                    document: Tuple[bytes, str, str]) -> None:
    raw, _type, name = document
    key = crypto.active_key(session, work.caller.hospital_id)
    file_id = new_id()
    size, sha256, content_type = files.store_bytes(raw, work.caller.hospital_id, file_id, key)
    work.stored_files.append(file_id)
    session.add(RecordFile(id=file_id, hospital_id=work.caller.hospital_id, patient_id=patient.id, record_id=record.id,
                           filename=name, content_type=content_type, size=size, sha256=sha256,
                           key_version=key.version, uploaded_by=None))
    session.flush()


def _write(session, work: Work, hospital: Hospital, kind: str, resource: Dict[str, Any], patient: Patient,
           item: Dict[str, Any], document: Optional[Tuple[bytes, str, str]]) -> EntryResult:
    caller = work.caller
    resource_id = resource.get("id")
    meta = resource.get("meta") if isinstance(resource.get("meta"), dict) else {}
    version_id = meta.get("versionId")
    version_id = str(version_id)[:64] if version_id is not None else None
    content_hash = item["import_key"]
    mode = "Test mode: nothing was stored. " if work.test else ""
    existing = None
    if resource_id is not None:
        existing = session.scalar(select(IntegrationResource).where(
            IntegrationResource.client_pk == caller.client_pk, IntegrationResource.resource_type == kind,
            IntegrationResource.resource_id == resource_id))
    if existing is not None:
        record = session.scalar(select(ClinicalRecord).where(ClinicalRecord.id == existing.record_id)
                                .with_for_update())
        if record.retracted:
            raise EntryFailed(409, "conflict", "This record was retracted at the hospital; send it with a new id.")
        if record.patient_id != patient.id or record.category != item["category"]:
            raise EntryFailed(409, "conflict", "A resource cannot move to another patient or kind of record; "
                                               "send it with a new id.")
        unchanged = (version_id is not None and version_id == existing.version_id) or \
            content_hash == existing.content_hash
        if unchanged:
            return EntryResult(200, _location(kind, record), f'W/"{record.version}"',
                               outcome("information", "informational", f"{mode}Already stored; nothing changed."))
        if work.test:
            return EntryResult(200, _location(kind, record), None, outcome(
                "information", "informational",
                f"{mode}This would correct record {record.id} (version {record.version + 1})."))
        record.title = item["title"]
        record.details = json.dumps(item["details"], ensure_ascii=False)
        record.occurred_at = datetime.fromisoformat(item["occurred_at"]).astimezone(timezone.utc)
        record.recorded_by_name = item["recorded_by"]
        if document is not None:
            for old in records.files_of(session, record.id):
                old.record_id = None  # back to the uploads, cleaned up later (as a portal correction does)
            session.flush()
            _store_document(session, work, record, patient, document)
        record.version += 1
        record.updated_at = utcnow()
        existing.version_id, existing.content_hash = version_id, content_hash
        records.publish(session, record, patient, hospital)
        _audit(session, caller, "integration_record_corrected", patient, record, kind)
        session.flush()
        return EntryResult(200, _location(kind, record), f'W/"{record.version}"')
    if resource_id is None:
        same = session.scalar(select(ClinicalRecord).where(
            ClinicalRecord.hospital_id == caller.hospital_id, ClinicalRecord.import_key == content_hash))
        if same is not None:
            return EntryResult(200, _location(kind, same), f'W/"{same.version}"',
                               outcome("information", "informational", f"{mode}Already stored; nothing changed."))
    if work.test:
        return EntryResult(201, None, None, outcome(
            "information", "informational",
            f"{mode}This would create a {item['category'].replace('_', ' ')} record for patient {patient.mrn}"
            f"{'' if patient.dedan_id else ' (not linked to Endod: kept at the hospital until linked)'}."))
    key_free = not imports.already_imported(session, caller.hospital_id, content_hash)
    record = imports.new_record(session, caller.hospital_id, patient,
                                {**item, "import_key": content_hash if key_free else None})
    if document is not None:
        _store_document(session, work, record, patient, document)
    if resource_id is not None:
        session.add(IntegrationResource(hospital_id=caller.hospital_id, client_pk=caller.client_pk,
                                        resource_type=kind, resource_id=resource_id, version_id=version_id,
                                        content_hash=content_hash, record_id=record.id))
    records.publish(session, record, patient, hospital)
    _audit(session, caller, "integration_record_created", patient, record, kind)
    session.flush()
    return EntryResult(201, _location(kind, record), f'W/"{record.version}"')


def _entry(session, work: Work, hospital: Hospital, planner: imports.Planner, index: int, entry: Any,
           patients: Dict[str, List[Dict[str, Any]]]) -> Optional[EntryResult]:
    """One entry's result (None for a Patient entry, used to find patients). Raises EntryFailed."""
    if not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict):
        raise EntryFailed(400, "structure", "The entry has no resource.")
    resource = entry["resource"]
    kind = resource.get("resourceType")
    if kind == "Patient":
        return EntryResult(200, None, None, outcome(
            "information", "informational", "Used to find the patient; patients are never created or changed."))
    request = entry.get("request")
    resource_id = resource.get("id")
    if resource_id is not None and (not isinstance(resource_id, str) or not _FHIR_ID.match(resource_id)):
        raise EntryFailed(400, "value", "The resource id must be 1 to 64 letters, digits, '-' or '.'.")
    if request is not None:
        method = request.get("method") if isinstance(request, dict) else None
        if method not in ("POST", "PUT"):
            raise EntryFailed(400, "not-supported", "Only POST (create) and PUT (create or correct) are accepted.")
        url = request.get("url")
        if method == "PUT" and (not resource_id or url != f"{kind}/{resource_id}"):
            raise EntryFailed(400, "value", "A PUT needs the resource's id, and request.url must be Type/id.")
    scope = scope_for(resource)
    if scope not in work.caller.scopes:
        raise EntryFailed(403, "forbidden", f"This connection may not send {kind} ({scope} is not granted).")
    try:
        patient, mapped = imports.map_resource(planner, resource, patients, imports.API_MAPPERS[kind])
    except imports.UnknownPatient as exc:
        raise EntryFailed(422, "not-found", f"Unknown patient: {exc}. Patients are matched by the hospital number "
                                            f"({planner.mrn_system}) or the Endod ID ({imports.ENDOD_SYSTEM}) "
                                            "and must already be registered at the hospital.") from None
    except imports.Skip as exc:
        raise EntryFailed(422, "invalid", str(exc)) from None
    except (AttributeError, TypeError, KeyError, ValueError):
        raise EntryFailed(422, "invalid", "The resource is malformed.") from None
    category, title, details, when, who = mapped[:5]
    document = mapped[5] if len(mapped) > 5 else None
    try:
        item = planner.prepare(index, f"{kind} {resource_id or ''}".strip(), patient, category, title, details,
                               planner.when(when), who, source=resource)
    except imports.Skip as exc:
        raise EntryFailed(422, "invalid", str(exc)) from None
    return _write(session, work, hospital, kind, resource, patient, item, document)


def parse_body(data: bytes) -> Dict[str, Any]:
    if len(data) > MAX_BODY_BYTES:
        raise FhirError(413, "too-costly", f"A request can be at most {MAX_BODY_BYTES // (1024 * 1024)} MB.")
    try:
        body = json.loads(data.decode("utf-8-sig"))
    except RecursionError:
        raise FhirError(400, "structure", "The JSON is nested too deeply.") from None
    except (UnicodeDecodeError, ValueError):
        raise FhirError(400, "structure", "The body is not valid JSON.") from None
    if imports._depth(body) > imports.MAX_JSON_DEPTH:
        raise FhirError(400, "structure", "The JSON is nested too deeply.")
    if not isinstance(body, dict):
        raise FhirError(400, "structure", "The body must be a FHIR resource (a JSON object).")
    return body


def request_hash(method: str, path: str, data: bytes) -> str:
    digest = hashlib.sha256()
    for part in (method.encode(), b"\n", path.encode(), b"\n", data):
        digest.update(part)
    return digest.hexdigest()


def _replay(session, caller: Caller, key: str, fingerprint: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    row = session.scalar(select(IntegrationIdempotency).where(
        IntegrationIdempotency.client_pk == caller.client_pk, IntegrationIdempotency.key == key,
        IntegrationIdempotency.created_at > utcnow() - IDEMPOTENCY_FOR))
    if row is None:
        return None
    if row.request_hash != fingerprint:
        raise FhirError(422, "conflict", "This Idempotency-Key was already used for a different request.")
    return row.status_code, json.loads(row.response)


def handle(caller: Caller, data: bytes, path_type: Optional[str], idempotency_key: Optional[str],
           method: str, path: str) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    """Process a write. Returns (status, body, headers). Raises FhirError."""
    if idempotency_key is not None and not 0 < len(idempotency_key) <= MAX_IDEMPOTENCY_KEY:
        raise FhirError(400, "value", f"The Idempotency-Key must be 1 to {MAX_IDEMPOTENCY_KEY} characters.")
    body = parse_body(data)
    single = path_type is not None
    if single:
        if body.get("resourceType") != path_type:
            raise FhirError(400, "value", f"The body must be a {path_type} (the type in the URL).")
        entries: List[Any] = [{"resource": body}]
        transaction = True
    else:
        if body.get("resourceType") != "Bundle" or body.get("type") not in ("transaction", "batch"):
            raise FhirError(400, "value", "Send a Bundle of type transaction or batch.")
        entries = body.get("entry") or []
        if not isinstance(entries, list):
            raise FhirError(400, "structure", "Bundle.entry must be a list.")
        if len(entries) > MAX_ENTRIES:
            raise FhirError(413, "too-costly", f"A bundle can have at most {MAX_ENTRIES} entries.")
        transaction = body["type"] == "transaction"
    fingerprint = request_hash(method, path, data)
    work = Work(caller=caller, test=caller.mode == IntegrationMode.TEST)
    try:
        status, response, headers = _run(work, entries, single, transaction, idempotency_key, fingerprint)
    except BaseException:
        for file_id in work.stored_files:
            files.delete(caller.hospital_id, file_id)
        raise
    return status, response, headers


def _run(work: Work, entries: List[Any], single: bool, transaction: bool, idempotency_key: Optional[str],
         fingerprint: str) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    caller = work.caller
    try:
        with session_scope(caller.hospital_id) as session:
            if idempotency_key is not None:
                replayed = _replay(session, caller, idempotency_key, fingerprint)
                if replayed is not None:
                    return replayed[0], replayed[1], {"Idempotent-Replayed": "true"}
            hospital = session.get(Hospital, caller.hospital_id)
            planner = imports.Planner(session, hospital, mrn_system=mrn_system(hospital), require_link=False)
            resources = [(i, (e or {}).get("fullUrl") if isinstance(e, dict) else None,
                          (e or {}).get("resource") if isinstance(e, dict) else None)
                         for i, e in enumerate(entries, start=1)]
            patients = imports.bundle_patients(resources)
            results: List[EntryResult] = []
            failures: List[Tuple[int, EntryFailed]] = []
            for index, entry in enumerate(entries):
                files_before = len(work.stored_files)
                try:
                    if transaction:
                        result = _entry(session, work, hospital, planner, index, entry, patients)
                    else:
                        with session.begin_nested():  # a failed entry leaves nothing behind
                            result = _entry(session, work, hospital, planner, index, entry, patients)
                except EntryFailed as exc:
                    if not transaction:  # its savepoint is gone: so are its files
                        for file_id in work.stored_files[files_before:]:
                            files.delete(caller.hospital_id, file_id)
                        del work.stored_files[files_before:]
                    failures.append((index, exc))
                    result = EntryResult(exc.status, None, None,
                                         outcome("error", exc.code, exc.message, f"Bundle.entry[{index}]"))
                results.append(result)
            status, response, headers = _respond(single, transaction, results, failures, work.test)
            if transaction and failures:
                session.rollback()
                for file_id in work.stored_files:
                    files.delete(caller.hospital_id, file_id)
                work.stored_files.clear()
            if idempotency_key is not None and not (transaction and failures):
                session.add(IntegrationIdempotency(
                    hospital_id=caller.hospital_id, client_pk=caller.client_pk, key=idempotency_key,
                    request_hash=fingerprint, status_code=status, response=json.dumps(response)))
            return status, response, headers
    except IntegrityError:
        # The same records, or the same Idempotency-Key, at the same moment: the
        # first one won; sending this again gets its answer.
        raise FhirError(409, "conflict", "The same request was being processed at the same time; send it again.") \
            from None


def _respond(single: bool, transaction: bool, results: List[EntryResult], failures: List[Tuple[int, EntryFailed]],
             test: bool) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    if single:
        result = results[0]
        if failures:
            failed = failures[0][1]
            return failed.status, outcome("error", failed.code, failed.message), {}
        headers = {"Location": result.location} if result.location else {}
        if result.etag:
            headers["ETag"] = result.etag
        body = result.outcome or outcome("information", "informational",
                                         "Stored." if result.status == 201 else "Updated.")
        return result.status, body, headers
    if transaction and failures:
        issues = [{"severity": "error", "code": exc.code, "diagnostics": exc.message[:500],
                   "expression": [f"Bundle.entry[{index}]"]} for index, exc in failures]
        status = 422 if all(exc.status == 422 for _i, exc in failures) else 400
        if all(exc.status == 403 for _i, exc in failures):
            status = 403
        return status, {"resourceType": "OperationOutcome", "issue": issues}, {}
    kind = "transaction-response" if transaction else "batch-response"
    bundle = {"resourceType": "Bundle", "type": kind, "entry": [{"response": r.response()} for r in results]}
    if test:
        bundle["meta"] = {"tag": [{"system": "https://endod-health.com/integrations", "code": "test-mode",
                                   "display": "Test mode: nothing was stored"}]}
    return 200, bundle, {}
