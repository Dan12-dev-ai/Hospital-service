"""Imports from hospitals with their own system (docs/history-events.md, section 6).

A FHIR R4 Bundle (JSON) or a CSV (docs/imports.md has the template) becomes a
*plan*: what will be imported, and what is skipped and why. Nothing is saved
until the plan is confirmed; then each item becomes a clinical record
(``source: "import"``) published like any other.

Patients are matched by the hospital number (MRN) or by the Endod identifier
``{"system": "https://endod-health.com/id", "value": "DE123456"}``, and must
be linked to Endod.
"""

from __future__ import annotations

import base64
import binascii
import csv
import io
import json
import re
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import files
from app.models import ClinicalRecord, Hospital, Patient, RecordCategory
from app.records import DetailsError, clean_details
from app.validation import normalize_dedan_id

ENDOD_SYSTEM = "https://endod-health.com/id"
MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_ITEMS = 500

CSV_COLUMNS = [
    "mrn", "endod_id", "category", "title", "occurred_at", "recorded_by",
    "condition", "icd10_code", "status",
    "drug", "dose", "route", "frequency", "duration", "quantity",
    "test", "value", "unit", "reference_range", "flag", "specimen",
    "modality", "body_part", "findings", "impression",
    "complaint", "plan", "notes",
]
CSV_CATEGORIES = (RecordCategory.DIAGNOSIS, RecordCategory.PRESCRIPTION, RecordCategory.LAB_RESULT,
                  RecordCategory.IMAGING, RecordCategory.VISIT_NOTE)


class ImportFailed(ValueError):
    """The whole file is unusable (not a bundle, too big, unreadable)."""


class Skip(ValueError):
    """One item cannot be imported; the message says why."""


class Planner:
    """Builds the plan: resolves patients and checks every item."""

    def __init__(self, session: Session, hospital: Hospital):
        self.session = session
        self.hospital = hospital
        self.zone = ZoneInfo(hospital.timezone)
        self.items: List[Dict[str, Any]] = []
        self.skipped: List[Dict[str, Any]] = []
        #: Inline documents, stored as staged files on confirmation of the preview.
        self.documents: Dict[int, Tuple[bytes, str, str]] = {}
        self._patients: Dict[Tuple[str, str], Optional[Patient]] = {}
        self._seen: set = set()

    # --- patients -------------------------------------------------------------
    def patient_by(self, mrn: Optional[str] = None, dedan_id: Optional[str] = None) -> Patient:
        if dedan_id:
            try:
                dedan = normalize_dedan_id(dedan_id)
            except ValueError as exc:
                raise Skip(f"{dedan_id!r} is not an Endod ID") from exc
            patient = self._lookup("dedan", dedan, Patient.dedan_id == dedan)
            if patient is None and not mrn:
                raise Skip(f"no patient here is linked to {dedan}")
            if patient is not None:
                return self._linked(patient)
        if mrn:
            value = mrn.strip().upper()
            patient = self._lookup("mrn", value, Patient.mrn == value)
            if patient is None:
                raise Skip(f"no patient with hospital number {value}")
            return self._linked(patient)
        raise Skip("no hospital number or Endod ID for the patient")

    def _lookup(self, kind: str, value: str, condition) -> Optional[Patient]:
        key = (kind, value)
        if key not in self._patients:
            self._patients[key] = self.session.scalar(select(Patient).where(
                Patient.hospital_id == self.hospital.id, condition))
        return self._patients[key]

    @staticmethod
    def _linked(patient: Patient) -> Patient:
        if not patient.dedan_id:
            raise Skip(f"{patient.full_name} ({patient.mrn}) is not linked to Endod")
        return patient

    # --- items ----------------------------------------------------------------
    def when(self, value: Any) -> datetime:
        """A FHIR date or dateTime (or the CSV's), in UTC. A date alone is
        midnight at the hospital; a time without an offset is the hospital's."""
        if not isinstance(value, str) or not value.strip():
            raise Skip("no date")
        text = value.strip().replace("Z", "+00:00")
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                moment = datetime.combine(date.fromisoformat(text), time.min, self.zone)
            else:
                moment = datetime.fromisoformat(text)
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=self.zone)
        except ValueError as exc:
            raise Skip(f"{value!r} is not a date") from exc
        if moment > datetime.now(timezone.utc):
            raise Skip("the date is in the future")
        return moment.astimezone(timezone.utc)

    def add(self, index: int, what: str, patient: Patient, category: str, title: str, details: Dict[str, Any],
            occurred_at: datetime, recorded_by: Optional[str], document: Optional[Tuple[bytes, str, str]] = None):
        title = (title or "").strip()[:200]
        if not title:
            raise Skip("no title")
        try:
            cleaned = clean_details(category, details)
        except DetailsError as exc:
            raise Skip(str(exc)) from exc
        key = (patient.id, category, title.lower(), occurred_at.isoformat())
        if key in self._seen:
            raise Skip("the same record appears twice in this file")
        self._seen.add(key)
        if self.session.scalar(select(ClinicalRecord.id).where(
                ClinicalRecord.patient_id == patient.id, ClinicalRecord.category == category,
                ClinicalRecord.title == title, ClinicalRecord.occurred_at == occurred_at,
                ClinicalRecord.source == "import", ClinicalRecord.retracted.is_(False))):
            raise Skip("already imported")
        item = {
            "index": index, "what": what, "patient_id": patient.id, "patient": f"{patient.full_name} ({patient.mrn})",
            "category": category, "title": title, "details": cleaned, "occurred_at": occurred_at.isoformat(),
            "recorded_by": (recorded_by or "").strip()[:160] or None, "file": None,
        }
        if document is not None:
            data, content_type, filename = document
            item["file"] = {"filename": filename, "content_type": content_type, "size": len(data)}
            self.documents[index] = document
        self.items.append(item)

    def skip(self, index: int, what: str, reason: str) -> None:
        self.skipped.append({"index": index, "what": what, "reason": reason})


# --- FHIR R4 ------------------------------------------------------------------------

def _text_of(concept: Any) -> Optional[str]:
    """A CodeableConcept's words: its text, else its first coding's display or code."""
    if not isinstance(concept, dict):
        return None
    if isinstance(concept.get("text"), str) and concept["text"].strip():
        return concept["text"].strip()
    for coding in concept.get("coding") or []:
        if isinstance(coding, dict):
            for key in ("display", "code"):
                if isinstance(coding.get(key), str) and coding[key].strip():
                    return coding[key].strip()
    return None


def _codes(concept: Any) -> List[Dict[str, Any]]:
    if not isinstance(concept, dict):
        return []
    return [c for c in concept.get("coding") or [] if isinstance(c, dict)]


def _first(values: Any) -> Any:
    return values[0] if isinstance(values, list) and values else None


def _display(ref: Any) -> Optional[str]:
    return ref.get("display") if isinstance(ref, dict) and isinstance(ref.get("display"), str) else None


def _notes(resource: Dict[str, Any]) -> Optional[str]:
    texts = [n.get("text") for n in resource.get("note") or [] if isinstance(n, dict) and isinstance(n.get("text"), str)]
    return "\n".join(texts) or None


def _quantity(q: Any) -> Optional[str]:
    if not isinstance(q, dict) or q.get("value") is None:
        return None
    unit = q.get("unit") or q.get("code") or ""
    return f"{q['value']} {unit}".strip()


def _category_has(resource: Dict[str, Any], *codes: str) -> bool:
    wanted = {c.lower() for c in codes}
    categories = resource.get("category")
    categories = categories if isinstance(categories, list) else [categories]
    for concept in categories:
        for coding in _codes(concept):
            if str(coding.get("code", "")).lower() in wanted:
                return True
        text = _text_of(concept)
        if text and text.lower() in wanted:
            return True
    return False


_CONDITION_STATUS = {"active": "active", "recurrence": "active", "relapse": "active",
                     "inactive": "resolved", "remission": "resolved", "resolved": "resolved"}
_FLAGS = {"L": "low", "LL": "critical", "LU": "critical", "N": "normal", "H": "high", "HH": "critical",
          "HU": "critical", "A": "high", "AA": "critical"}


def _condition(r: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any], Any, Optional[str]]:
    condition = _text_of(r.get("code"))
    if not condition:
        raise Skip("the condition has no name")
    icd = next((str(c.get("code")) for c in _codes(r.get("code"))
                if "icd-10" in str(c.get("system", "")).lower() and c.get("code")), None)
    status_code = str((_first(_codes(r.get("clinicalStatus"))) or {}).get("code", "")).lower()
    status = _CONDITION_STATUS.get(status_code, "active")
    if any(str(c.get("code")).lower() == "chronic" for c in _codes(_first(r.get("category")))):
        status = "chronic"
    onset_period = r.get("onsetPeriod") if isinstance(r.get("onsetPeriod"), dict) else {}
    when = r.get("onsetDateTime") or onset_period.get("start") or r.get("recordedDate")
    return (RecordCategory.DIAGNOSIS, condition,
            {"condition": condition, "code": icd, "status": status, "notes": _notes(r)},
            when, _display(r.get("recorder")) or _display(r.get("asserter")))


def _medication(r: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any], Any, Optional[str]]:
    drug = _text_of(r.get("medicationCodeableConcept")) or _display(r.get("medicationReference"))
    if not drug:
        raise Skip("the medication has no name")
    dosage = _first(r.get("dosageInstruction")) or _first(r.get("dosage")) or {}
    dose_rate = _first(dosage.get("doseAndRate")) or {}
    repeat = (dosage.get("timing") or {}).get("repeat") or {}
    frequency = _text_of((dosage.get("timing") or {}).get("code"))
    if not frequency and repeat.get("frequency"):
        frequency = f"{repeat.get('frequency')} times every {repeat.get('period', 1)} {repeat.get('periodUnit', 'd')}"
    duration = None
    if repeat.get("boundsDuration"):
        duration = _quantity(repeat["boundsDuration"])
    supply = (r.get("dispenseRequest") or {})
    item = {
        "drug": drug,
        "dose": _quantity(dose_rate.get("doseQuantity")) or dosage.get("text"),
        "route": _text_of(dosage.get("route")),
        "frequency": frequency,
        "duration": duration or _quantity(supply.get("expectedSupplyDuration")),
        "quantity": _quantity(supply.get("quantity")),
        "notes": dosage.get("patientInstruction"),
    }
    when = r.get("authoredOn") or r.get("effectiveDateTime") or r.get("dateAsserted") \
        or (r.get("effectivePeriod") or {}).get("start")
    who = _display(r.get("requester")) or _display(r.get("informationSource"))
    return RecordCategory.PRESCRIPTION, f"Prescription: {drug}", {"items": [item], "notes": _notes(r)}, when, who


def _observation(r: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any], Any, Optional[str]]:
    if not _category_has(r, "laboratory"):
        raise Skip("not a laboratory observation")
    test = _text_of(r.get("code"))
    if not test:
        raise Skip("the test has no name")
    value, unit = None, None
    if isinstance(r.get("valueQuantity"), dict):
        value, unit = r["valueQuantity"].get("value"), r["valueQuantity"].get("unit") or r["valueQuantity"].get("code")
    elif r.get("valueString") is not None:
        value = r["valueString"]
    elif r.get("valueCodeableConcept") is not None:
        value = _text_of(r["valueCodeableConcept"])
    elif r.get("valueBoolean") is not None:
        value = "positive" if r["valueBoolean"] else "negative"
    elif r.get("valueInteger") is not None:
        value = r["valueInteger"]
    reference = _first(r.get("referenceRange")) or {}
    reference_range = reference.get("text")
    if not reference_range and (reference.get("low") or reference.get("high")):
        low = (reference.get("low") or {}).get("value")
        high = (reference.get("high") or {}).get("value")
        reference_range = f"{'' if low is None else low}-{'' if high is None else high}"
    flag_code = str((_first(_codes(_first(r.get("interpretation")))) or {}).get("code", "")).upper()
    item = {"test": test, "value": value, "unit": unit, "reference_range": reference_range,
            "flag": _FLAGS.get(flag_code)}
    when = r.get("effectiveDateTime") or r.get("issued") or (r.get("effectivePeriod") or {}).get("start")
    return (RecordCategory.LAB_RESULT, test,
            {"items": [item], "specimen": _display(r.get("specimen")), "notes": _notes(r)},
            when, _display(_first(r.get("performer"))))


def _report(r: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any], Any, Optional[str]]:
    if not _category_has(r, "rad", "imaging", "radiology", "LP29684-5"):
        raise Skip("not an imaging report")
    name = _text_of(r.get("code")) or "Imaging report"
    modality = next((c.get("display") or c.get("code") for c in _codes(_first(r.get("category")))
                     if str(c.get("code", "")).upper() not in ("RAD", "LP29684-5")), None)
    details = {"modality": modality or name, "body_part": None,
               "findings": r.get("conclusion"), "impression": _text_of(_first(r.get("conclusionCode")))}
    when = r.get("effectiveDateTime") or r.get("issued") or (r.get("effectivePeriod") or {}).get("start")
    return RecordCategory.IMAGING, name, details, when, _display(_first(r.get("performer")))


def _document(r: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any], Any, Optional[str], Tuple[bytes, str, str]]:
    attachment = (_first(r.get("content")) or {}).get("attachment") or {}
    data = attachment.get("data")
    if not isinstance(data, str) or not data:
        raise Skip("the document is not attached inline (base64)")
    if len(data) > (files.MAX_FILE_BYTES * 4) // 3 + 4:
        raise Skip("the document is larger than 20 MB")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise Skip("the attachment is not valid base64") from exc
    content_type = files.sniff(raw[:16])
    if content_type is None:
        raise Skip("only PDF, JPEG, PNG or WebP documents can be imported")
    try:
        filename = files.safe_filename(attachment.get("title") or "document", content_type)
    except files.FileRejected as exc:
        raise Skip(str(exc)) from exc
    title = r.get("description") or attachment.get("title") or _text_of(r.get("type")) or "Document"
    when = r.get("date") or attachment.get("creation") or ((r.get("context") or {}).get("period") or {}).get("start")
    return (RecordCategory.DOCUMENT, title, {"description": r.get("description")}, when,
            _display(_first(r.get("author"))), (raw, content_type, filename))


MAPPERS = {
    "Condition": _condition,
    "MedicationRequest": _medication,
    "MedicationStatement": _medication,
    "Observation": _observation,
    "DiagnosticReport": _report,
    "DocumentReference": _document,
}


def plan_fhir(planner: Planner, data: bytes) -> None:
    try:
        bundle = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ImportFailed("The file is not valid JSON.") from exc
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise ImportFailed("The JSON is not a FHIR Bundle (resourceType must be \"Bundle\").")
    entries = bundle.get("entry") or []
    if not isinstance(entries, list):
        raise ImportFailed("The bundle's entry is not a list.")
    if len(entries) > MAX_ITEMS:
        raise ImportFailed(f"A bundle can have at most {MAX_ITEMS} entries.")
    resources = [(i, (e or {}).get("fullUrl"), (e or {}).get("resource")) for i, e in enumerate(entries, start=1)
                 if isinstance(e, dict)]
    patients: Dict[str, List[Dict[str, Any]]] = {}
    for _i, full_url, r in resources:
        if isinstance(r, dict) and r.get("resourceType") == "Patient":
            identifiers = [x for x in r.get("identifier") or [] if isinstance(x, dict)]
            for ref in (full_url, f"Patient/{r.get('id')}" if r.get("id") else None):
                if ref:
                    patients[ref] = identifiers
    for index, _full_url, r in resources:
        if not isinstance(r, dict):
            planner.skip(index, "entry", "no resource")
            continue
        kind = r.get("resourceType") or "?"
        what = f"{kind} {r.get('id') or ''}".strip()
        if kind == "Patient":
            continue  # used to find the patient of the other entries
        mapper = MAPPERS.get(kind)
        if mapper is None:
            planner.skip(index, what, f"{kind} is not imported")
            continue
        try:
            patient = _subject(planner, r, patients)
            mapped = mapper(r)
            category, title, details, when, who = mapped[:5]
            planner.add(index, what, patient, category, title, details, planner.when(when), who,
                        mapped[5] if len(mapped) > 5 else None)
        except Skip as exc:
            planner.skip(index, what, str(exc))
        except (AttributeError, TypeError, KeyError, ValueError):
            planner.skip(index, what, "the resource is malformed")


def _subject(planner: Planner, r: Dict[str, Any], patients: Dict[str, List[Dict[str, Any]]]) -> Patient:
    subject = r.get("subject") or r.get("patient")
    if not isinstance(subject, dict):
        raise Skip("no patient (subject)")
    identifiers: List[Dict[str, Any]] = []
    if isinstance(subject.get("identifier"), dict):
        identifiers = [subject["identifier"]]
    elif isinstance(subject.get("reference"), str):
        identifiers = patients.get(subject["reference"], [])
        if not identifiers:
            raise Skip(f"patient {subject['reference']} is not in the bundle")
    dedan = next((str(x.get("value")) for x in identifiers if x.get("system") == ENDOD_SYSTEM and x.get("value")), None)
    others = [str(x.get("value")) for x in identifiers if x.get("system") != ENDOD_SYSTEM and x.get("value")]
    if dedan:
        try:
            return planner.patient_by(dedan_id=dedan)
        except Skip:
            if not others:
                raise
    last: Optional[Skip] = None
    for value in others:
        try:
            return planner.patient_by(mrn=value)
        except Skip as exc:
            last = exc
    raise last or Skip("no hospital number or Endod ID for the patient")


# --- CSV ---------------------------------------------------------------------------------

def plan_csv(planner: Planner, data: bytes) -> None:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportFailed("The CSV must be UTF-8 text.") from exc
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip().lower() for h in reader.fieldnames or []]
    if "category" not in header or "occurred_at" not in header or not ({"mrn", "endod_id"} & set(header)):
        raise ImportFailed("The CSV header must include category, occurred_at, and mrn or endod_id "
                           "(see the template).")
    reader.fieldnames = header
    for row_number, row in enumerate(reader, start=2):
        if row_number - 1 > MAX_ITEMS:
            raise ImportFailed(f"A CSV can have at most {MAX_ITEMS} rows.")
        row = {k: (v or "").strip() for k, v in row.items() if isinstance(k, str)}
        if not any(row.values()):
            continue
        what = f"row {row_number}"
        try:
            category = row.get("category", "").lower()
            if category not in CSV_CATEGORIES:
                raise Skip(f"category must be one of {', '.join(CSV_CATEGORIES)}")
            patient = planner.patient_by(mrn=row.get("mrn") or None, dedan_id=row.get("endod_id") or None)
            title, details = _csv_details(category, row)
            planner.add(row_number, what, patient, category, title, details, planner.when(row.get("occurred_at")),
                        row.get("recorded_by"))
        except Skip as exc:
            planner.skip(row_number, what, str(exc))


def _csv_details(category: str, row: Dict[str, str]) -> Tuple[str, Dict[str, Any]]:
    g = row.get
    if category == RecordCategory.DIAGNOSIS:
        return g("title") or g("condition", ""), {
            "condition": g("condition") or g("title"), "code": g("icd10_code"), "status": g("status") or "active",
            "notes": g("notes")}
    if category == RecordCategory.PRESCRIPTION:
        return g("title") or f"Prescription: {g('drug', '')}", {"items": [{
            "drug": g("drug"), "dose": g("dose"), "route": g("route"), "frequency": g("frequency"),
            "duration": g("duration"), "quantity": g("quantity")}], "notes": g("notes")}
    if category == RecordCategory.LAB_RESULT:
        return g("title") or g("test", ""), {"items": [{
            "test": g("test"), "value": g("value"), "unit": g("unit"), "reference_range": g("reference_range"),
            "flag": (g("flag") or "").lower() or None}], "specimen": g("specimen"), "notes": g("notes")}
    if category == RecordCategory.IMAGING:
        return g("title") or g("modality", ""), {
            "modality": g("modality"), "body_part": g("body_part"), "findings": g("findings"),
            "impression": g("impression")}
    return g("title") or "Visit note", {"complaint": g("complaint"), "findings": g("findings"), "plan": g("plan")}


def plan(session: Session, hospital: Hospital, data: bytes, kind: str) -> Planner:
    if len(data) > MAX_IMPORT_BYTES:
        raise ImportFailed(f"An import file can be at most {MAX_IMPORT_BYTES // (1024 * 1024)} MB.")
    planner = Planner(session, hospital)
    (plan_fhir if kind == "fhir" else plan_csv)(planner, data)
    return planner


def detect(content_type: str, filename: str, data: bytes) -> str:
    """'fhir' or 'csv', from the declared type, the name and the content."""
    name = (filename or "").lower()
    if "json" in content_type or name.endswith(".json"):
        return "fhir"
    if "csv" in content_type or name.endswith(".csv") or "text/plain" in content_type:
        return "csv"
    return "fhir" if data.lstrip()[:1] == b"{" else "csv"


def template() -> str:
    return ",".join(CSV_COLUMNS) + "\n"
