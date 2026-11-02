"""The FHIR side of the OpenAPI document: for each resource Endod accepts,
the fields it reads (JSON Schema, field by field), realistic examples (those
of docs/integrations.md) and the answers.

Only what Endod reads is described; other FHIR fields are accepted and
ignored (``additionalProperties`` is left open on purpose).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

from app.integrations import scopes as S

FHIR_JSON = "application/fhir+json"
MRN_SYSTEM_EXAMPLE = "https://endod-health.com/hospital/sph/mrn"
ENDOD_SYSTEM = "https://endod-health.com/id"
SUBJECT = {"identifier": {"system": MRN_SYSTEM_EXAMPLE, "value": "SPH-000124"}}


def _ref(name: str) -> Dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


# --- shared datatypes -------------------------------------------------------------------------------------

DATATYPES: Dict[str, Dict[str, Any]] = {
    "FhirCoding": {"type": "object", "description": "A code from a code system.", "properties": {
        "system": {"type": "string", "description": "e.g. http://loinc.org, http://hl7.org/fhir/sid/icd-10."},
        "code": {"type": "string"}, "display": {"type": "string"}}},
    "FhirCodeableConcept": {"type": "object", "description": "Endod shows `text`, else the first coding's display "
                                                             "or code.", "properties": {
        "coding": {"type": "array", "items": _ref("FhirCoding")}, "text": {"type": "string"}}},
    "FhirQuantity": {"type": "object", "properties": {
        "value": {"type": "number"}, "unit": {"type": "string"}, "code": {"type": "string"},
        "system": {"type": "string"}}},
    "FhirIdentifier": {"type": "object", "required": ["system", "value"], "properties": {
        "system": {"type": "string", "description": f"The hospital's MRN system (e.g. {MRN_SYSTEM_EXAMPLE}) or "
                                                    f"{ENDOD_SYSTEM} for the Endod ID."},
        "value": {"type": "string", "description": "The hospital number (e.g. SPH-000124) or Endod ID (DE482731)."}}},
    "FhirSubject": {"type": "object", "description": "The patient, already registered at the hospital: by "
                                                     "`identifier` (hospital number or Endod ID), or by `reference` "
                                                     "to a Patient entry of the same Bundle (urn:uuid:...) that "
                                                     "carries such identifiers. Never matched by name.",
                    "properties": {"identifier": _ref("FhirIdentifier"),
                                   "reference": {"type": "string", "example": "urn:uuid:6d1c..."},
                                   "display": {"type": "string", "description": "Ignored for matching."}}},
    "FhirDisplayReference": {"type": "object", "description": "Endod reads `display` (the clinician's name, shown "
                                                              "to the patient).",
                             "properties": {"display": {"type": "string"}, "reference": {"type": "string"}}},
    "FhirMeta": {"type": "object", "properties": {
        "versionId": {"type": "string", "description": "Your version: the same id with a new versionId corrects "
                                                       "the record; the same versionId again changes nothing."},
        "lastUpdated": {"type": "string", "format": "date-time"}}},
}

_COMMON = {
    "id": {"type": "string", "pattern": "^[A-Za-z0-9\\-.]{1,64}$",
           "description": "Your id for the resource (optional). With it, sending it again corrects the record "
                          "(see meta.versionId)."},
    "meta": _ref("FhirMeta"),
    "subject": _ref("FhirSubject"),
}
_DATE = {"type": "string", "description": "A date or date-time; not in the future. A date without a time is "
                                          "midnight at the hospital; a time without an offset is the hospital's."}
_CATEGORY = {"type": "array", "items": _ref("FhirCodeableConcept")}


def _resource(name: str, description: str, required: List[str], props: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "object", "title": name, "description": description, "required": ["resourceType", *required],
            "properties": {"resourceType": {"type": "string", "enum": [name]}, **_COMMON, **props},
            "additionalProperties": True}


RESOURCES: Dict[str, Dict[str, Any]] = {
    "Observation": _resource(
        "Observation", "A laboratory result (category `laboratory`). Scope records.labs.write.",
        ["category", "code", "subject"], {
            "status": {"type": "string", "example": "final"},
            "category": {**_CATEGORY, "description": "Must include the code `laboratory` "
                                                     "(observation-category)."},
            "code": {**_ref("FhirCodeableConcept"), "description": "The test (e.g. LOINC 718-7, text "
                                                                   "\"Hemoglobin\"). Required."},
            "effectiveDateTime": {**_DATE, "description": "When the specimen was taken (or `issued`, or "
                                                          "effectivePeriod.start). Required."},
            "issued": _DATE,
            "valueQuantity": _ref("FhirQuantity"), "valueString": {"type": "string"},
            "valueCodeableConcept": _ref("FhirCodeableConcept"), "valueBoolean": {"type": "boolean"},
            "valueInteger": {"type": "integer"},
            "referenceRange": {"type": "array", "items": {"type": "object", "properties": {
                "low": _ref("FhirQuantity"), "high": _ref("FhirQuantity"), "text": {"type": "string"}}}},
            "interpretation": {"type": "array", "items": _ref("FhirCodeableConcept"),
                               "description": "L, N, H, or LL/HH/AA (critical) become the result's flag."},
            "specimen": _ref("FhirDisplayReference"),
            "performer": {"type": "array", "items": _ref("FhirDisplayReference")},
            "note": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string"}}}},
        }),
    "DiagnosticReport": _resource(
        "DiagnosticReport", "A lab panel (category `LAB`, scope records.labs.write: its contained Observations are "
                            "its tests) or an imaging report (category `RAD`, scope records.imaging.write: "
                            "`conclusion` is the findings, conclusionCode the impression).",
        ["category", "code", "subject"], {
            "status": {"type": "string", "example": "final"},
            "category": {**_CATEGORY, "description": "`LAB` (or LOINC LP29693-6) for a lab panel; `RAD` (or "
                                                     "LP29684-5) for imaging, with the modality (CT, MR, US, ...) "
                                                     "as another coding."},
            "code": {**_ref("FhirCodeableConcept"), "description": "The panel or study. Required for a lab panel."},
            "effectiveDateTime": {**_DATE, "description": "When (or `issued`, or effectivePeriod.start). Required."},
            "issued": _DATE,
            "conclusion": {"type": "string", "description": "Lab: the panel's notes; imaging: the findings."},
            "conclusionCode": {"type": "array", "items": _ref("FhirCodeableConcept"),
                               "description": "Imaging: the impression."},
            "contained": {"type": "array", "description": "Lab panel: its tests, as Observations (code and value).",
                          "items": {"type": "object"}},
            "specimen": {"type": "array", "items": _ref("FhirDisplayReference")},
            "performer": {"type": "array", "items": _ref("FhirDisplayReference")},
        }),
    "MedicationRequest": _resource(
        "MedicationRequest", "A prescription (one medicine per resource). Scope records.prescriptions.write. "
                             "Pharmacies dispense it through Endod (GET /prescriptions/{id}, webhook "
                             "prescription.dispensed).",
        ["subject"], {
            "status": {"type": "string", "example": "active"}, "intent": {"type": "string", "example": "order"},
            "medicationCodeableConcept": {**_ref("FhirCodeableConcept"),
                                          "description": "The medicine (or medicationReference.display). Required."},
            "medicationReference": _ref("FhirDisplayReference"),
            "authoredOn": {**_DATE, "description": "When prescribed. Required."},
            "requester": {**_ref("FhirDisplayReference"), "description": "The prescriber, shown to the patient."},
            "dosageInstruction": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string", "description": "The dose, if no doseQuantity."},
                "patientInstruction": {"type": "string"},
                "timing": {"type": "object", "properties": {
                    "code": _ref("FhirCodeableConcept"),
                    "repeat": {"type": "object", "properties": {
                        "frequency": {"type": "integer"}, "period": {"type": "number"},
                        "periodUnit": {"type": "string"}, "boundsDuration": _ref("FhirQuantity")}}}},
                "route": _ref("FhirCodeableConcept"),
                "doseAndRate": {"type": "array", "items": {"type": "object", "properties": {
                    "doseQuantity": _ref("FhirQuantity")}}}}}},
            "dispenseRequest": {"type": "object", "properties": {
                "quantity": {**_ref("FhirQuantity"), "description": "What the pharmacy gives (its number is what "
                                                                   "dispensing counts)."},
                "expectedSupplyDuration": _ref("FhirQuantity")}},
        }),
    "Condition": _resource(
        "Condition", "A diagnosis. Scope records.diagnoses.write.", ["code", "subject"], {
            "code": {**_ref("FhirCodeableConcept"), "description": "The diagnosis; an ICD-10 coding is kept. "
                                                                  "Required."},
            "clinicalStatus": {**_ref("FhirCodeableConcept"), "description": "active, resolved, ..."},
            "category": {**_CATEGORY, "description": "A `chronic` code marks it chronic."},
            "onsetDateTime": _DATE, "onsetPeriod": {"type": "object", "properties": {"start": _DATE}},
            "recordedDate": {**_DATE, "description": "When (or onsetDateTime / onsetPeriod.start). Required."},
            "recorder": _ref("FhirDisplayReference"), "asserter": _ref("FhirDisplayReference"),
        }),
    "Encounter": _resource(
        "Encounter", "A visit note: the reason, the diagnoses' names and the discharge disposition become the "
                     "note. Scope records.visits.write.", ["subject", "period"], {
            "status": {"type": "string", "example": "finished"},
            "class": {"type": "object", "properties": {"code": {"type": "string"}, "display": {"type": "string"}}},
            "type": {"type": "array", "items": _ref("FhirCodeableConcept"), "description": "The kind of visit."},
            "period": {"type": "object", "required": ["start"], "properties": {"start": _DATE, "end": _DATE}},
            "reasonCode": {"type": "array", "items": _ref("FhirCodeableConcept")},
            "diagnosis": {"type": "array", "items": {"type": "object", "properties": {
                "condition": _ref("FhirDisplayReference")}}},
            "hospitalization": {"type": "object", "properties": {
                "dischargeDisposition": _ref("FhirCodeableConcept")}},
            "participant": {"type": "array", "items": {"type": "object", "properties": {
                "individual": _ref("FhirDisplayReference")}}},
        }),
    "DocumentReference": _resource(
        "DocumentReference", "A document: PDF, JPEG, PNG or WebP, base64 inline, recognised by its content, at "
                             "most 10 MB per request. Scope records.documents.write.", ["content", "subject"], {
            "status": {"type": "string", "example": "current"},
            "description": {"type": "string", "description": "The document's title in the patient's app."},
            "type": _ref("FhirCodeableConcept"),
            "date": {**_DATE, "description": "When (or attachment.creation, or context.period.start). Required."},
            "author": {"type": "array", "items": _ref("FhirDisplayReference")},
            "content": {"type": "array", "minItems": 1, "items": {"type": "object", "properties": {
                "attachment": {"type": "object", "required": ["data"], "properties": {
                    "contentType": {"type": "string", "example": "application/pdf"},
                    "title": {"type": "string", "description": "The file name."},
                    "data": {"type": "string", "format": "byte", "description": "The file, base64."},
                    "creation": _DATE}}}}},
        }),
}

PATIENT_ENTRY = {"type": "object", "title": "Patient (bundle entry only)", "description":
                 "Only inside a Bundle, to name the patient for other entries (subject.reference to its fullUrl). "
                 "Patients are never created or changed through FHIR: register them with POST /patients.",
                 "required": ["resourceType", "identifier"], "properties": {
                     "resourceType": {"type": "string", "enum": ["Patient"]},
                     "identifier": {"type": "array", "items": _ref("FhirIdentifier")}}}

# --- examples (docs/integrations.md) --------------------------------------------------------------------

LAB_OBSERVATION = {
    "resourceType": "Observation", "id": "hb-000123", "meta": {"versionId": "1"}, "status": "final",
    "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                              "code": "laboratory"}]}],
    "code": {"coding": [{"system": "http://loinc.org", "code": "718-7"}], "text": "Hemoglobin"},
    "subject": SUBJECT, "effectiveDateTime": "2026-10-01T09:30:00+03:00",
    "valueQuantity": {"value": 13.2, "unit": "g/dL"},
    "referenceRange": [{"low": {"value": 12}, "high": {"value": 16}}], "interpretation": [{"coding": [{"code": "N"}]}],
}
LAB_REPORT = {
    "resourceType": "DiagnosticReport", "status": "final", "category": [{"coding": [{"code": "LAB"}]}],
    "code": {"text": "Complete blood count"},
    "subject": {"identifier": {"system": ENDOD_SYSTEM, "value": "DE482731"}},
    "effectiveDateTime": "2026-10-01T09:30:00+03:00", "conclusion": "Within normal limits",
    "contained": [
        {"resourceType": "Observation", "code": {"text": "WBC"}, "valueQuantity": {"value": 6.1, "unit": "10*3/uL"}},
        {"resourceType": "Observation", "code": {"text": "Platelets"},
         "valueQuantity": {"value": 250, "unit": "10*3/uL"}}],
}
RAD_REPORT = {
    "resourceType": "DiagnosticReport", "status": "final",
    "category": [{"coding": [{"code": "RAD"}, {"code": "CT", "display": "CT"}]}],
    "code": {"text": "CT head without contrast"}, "subject": SUBJECT, "issued": "2026-10-01T11:00:00+03:00",
    "conclusion": "No acute intracranial bleed.", "conclusionCode": [{"text": "Normal study"}],
}
PRESCRIPTION = {
    "resourceType": "MedicationRequest", "status": "active", "intent": "order",
    "medicationCodeableConcept": {"text": "Amoxicillin 500 mg capsule"}, "subject": SUBJECT,
    "authoredOn": "2026-10-01", "requester": {"display": "Dr. Abebe Kebede"},
    "dosageInstruction": [{"text": "1 capsule three times a day", "timing": {"repeat": {
        "frequency": 3, "period": 1, "periodUnit": "d", "boundsDuration": {"value": 7, "unit": "days"}}},
        "route": {"text": "oral"}}],
    "dispenseRequest": {"quantity": {"value": 21, "unit": "capsules"}},
}
CONDITION = {
    "resourceType": "Condition",
    "code": {"text": "Malaria", "coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "B54"}]},
    "clinicalStatus": {"coding": [{"code": "active"}]}, "subject": SUBJECT, "recordedDate": "2026-10-01",
    "recorder": {"display": "Dr. Abebe Kebede"},
}
ENCOUNTER = {
    "resourceType": "Encounter", "status": "finished", "class": {"code": "AMB", "display": "ambulatory"},
    "type": [{"text": "Outpatient visit"}], "subject": SUBJECT, "period": {"start": "2026-10-01T08:00:00+03:00"},
    "reasonCode": [{"text": "Fever for 3 days"}], "diagnosis": [{"condition": {"display": "Malaria"}}],
    "hospitalization": {"dischargeDisposition": {"text": "Home; review in 1 week"}},
    "participant": [{"individual": {"display": "Dr. Abebe Kebede"}}],
}
DOCUMENT = {
    "resourceType": "DocumentReference", "status": "current", "subject": SUBJECT, "description": "Discharge summary",
    "date": "2026-10-02T10:00:00+03:00",
    "content": [{"attachment": {"contentType": "application/pdf", "title": "discharge-summary.pdf",
                                "data": "JVBERi0xLjQK..."}}],
}

EXAMPLES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "Observation": {"hemoglobin": {"summary": "A lab result (with your id and version)", "value": LAB_OBSERVATION}},
    "DiagnosticReport": {
        "lab_panel": {"summary": "LAB: a lab panel (records.labs.write)", "value": LAB_REPORT},
        "imaging": {"summary": "RAD: an imaging report (records.imaging.write)", "value": RAD_REPORT}},
    "MedicationRequest": {"amoxicillin": {"summary": "A prescription", "value": PRESCRIPTION}},
    "Condition": {"malaria": {"summary": "A diagnosis", "value": CONDITION}},
    "Encounter": {"outpatient": {"summary": "A visit note", "value": ENCOUNTER}},
    "DocumentReference": {"pdf": {"summary": "A PDF document", "value": DOCUMENT}},
}

SCOPE_OF: Dict[str, List[str]] = {
    "Observation": [S.LABS], "DiagnosticReport": [S.LABS, S.IMAGING], "MedicationRequest": [S.PRESCRIPTIONS],
    "Condition": [S.DIAGNOSES], "Encounter": [S.VISITS], "DocumentReference": [S.DOCUMENTS],
}


def outcome_example(code: str, message: str, severity: str = "error", expression: str = "") -> Dict[str, Any]:
    issue: Dict[str, Any] = {"severity": severity, "code": code, "diagnostics": message}
    if expression:
        issue["expression"] = [expression]
    return {"resourceType": "OperationOutcome", "issue": [issue]}


# --- bundles ------------------------------------------------------------------------------------------------

BUNDLE_SCHEMA = {
    "type": "object", "title": "Bundle", "required": ["resourceType", "type", "entry"],
    "description": "At most 100 entries and 10 MB. `transaction`: all or nothing; `batch`: each entry on its own.",
    "properties": {
        "resourceType": {"type": "string", "enum": ["Bundle"]},
        "type": {"type": "string", "enum": ["transaction", "batch"]},
        "entry": {"type": "array", "maxItems": 100, "items": {"type": "object", "required": ["resource"],
                  "properties": {
                      "fullUrl": {"type": "string", "description": "urn:uuid:... for a Patient entry that other "
                                                                   "entries reference."},
                      "resource": {"oneOf": [_ref("FhirObservation"), _ref("FhirDiagnosticReport"),
                                             _ref("FhirMedicationRequest"), _ref("FhirCondition"),
                                             _ref("FhirEncounter"), _ref("FhirDocumentReference"),
                                             _ref("FhirPatientEntry")]},
                      "request": {"type": "object", "properties": {
                          "method": {"type": "string", "enum": ["POST", "PUT"],
                                     "description": "PUT (create or correct) needs the resource's id."},
                          "url": {"type": "string", "description": "Type for POST; Type/id for PUT."}}}}}}},
}
BUNDLE_RESPONSE_SCHEMA = {
    "type": "object", "title": "Bundle response", "required": ["resourceType", "type", "entry"],
    "properties": {
        "resourceType": {"type": "string", "enum": ["Bundle"]},
        "type": {"type": "string", "enum": ["transaction-response", "batch-response"]},
        "meta": {"type": "object", "description": "Test connections: tagged `test-mode` (nothing was stored)."},
        "entry": {"type": "array", "description": "One per entry sent, in order.", "items": {
            "type": "object", "properties": {"response": {"type": "object", "properties": {
                "status": {"type": "string", "example": "201 Created",
                           "description": "201 Created, 200 OK (a correction or a repeat), or an error status "
                                          "(batch)."},
                "location": {"type": "string", "example": "Observation/5f0c1e2d3c4b5a69788796a5b4c3d2e1/_history/1",
                             "description": "Type/<Endod record id>/_history/<version>: read it back with GET "
                                            "/fhir/Type/<id>."},
                "etag": {"type": "string", "example": "W/\"1\""},
                "outcome": _ref("OperationOutcome")}}}}},
    },
}

BUNDLE_EXAMPLES = {
    "transaction": {"summary": "A transaction: a lab result, by PUT with your id", "value": {
        "resourceType": "Bundle", "type": "transaction",
        "entry": [{"request": {"method": "PUT", "url": "Observation/hb-000123"}, "resource": LAB_OBSERVATION}]}},
    "batch": {"summary": "A batch naming the patient once (a Patient entry) for two records", "value": {
        "resourceType": "Bundle", "type": "batch", "entry": [
            {"fullUrl": "urn:uuid:6d1c0b5e-3f7a-4c1b-9a2e-1f0c8d7e6b5a", "resource": {
                "resourceType": "Patient", "identifier": [{"system": MRN_SYSTEM_EXAMPLE, "value": "SPH-000124"}]}},
            {"request": {"method": "POST", "url": "Condition"}, "resource": {
                **CONDITION, "subject": {"reference": "urn:uuid:6d1c0b5e-3f7a-4c1b-9a2e-1f0c8d7e6b5a"}}},
            {"request": {"method": "POST", "url": "MedicationRequest"}, "resource": {
                **PRESCRIPTION, "subject": {"reference": "urn:uuid:6d1c0b5e-3f7a-4c1b-9a2e-1f0c8d7e6b5a"}}}]}},
}
BUNDLE_RESPONSE_EXAMPLES = {
    "transaction": {"summary": "transaction-response", "value": {
        "resourceType": "Bundle", "type": "transaction-response", "entry": [{"response": {
            "status": "201 Created", "location": "Observation/5f0c1e2d3c4b5a69788796a5b4c3d2e1/_history/1",
            "etag": "W/\"1\""}}]}},
    "batch": {"summary": "batch-response (one entry failed)", "value": {
        "resourceType": "Bundle", "type": "batch-response", "entry": [
            {"response": {"status": "200 OK", "outcome": outcome_example(
                "informational", "Used to find the patient; patients are never created or changed.",
                severity="information")}},
            {"response": {"status": "201 Created",
                          "location": "Condition/0a1b2c3d4e5f60718293a4b5c6d7e8f9/_history/1", "etag": "W/\"1\""}},
            {"response": {"status": "422 Unprocessable Entity", "outcome": outcome_example(
                "invalid", "The date is in the future.", expression="Bundle.entry[2]")}}]}},
    "test_mode": {"summary": "Test connection: nothing stored", "value": {
        "resourceType": "Bundle", "type": "transaction-response",
        "meta": {"tag": [{"system": "https://endod-health.com/integrations", "code": "test-mode",
                          "display": "Test mode: nothing was stored"}]},
        "entry": [{"response": {"status": "201 Created", "outcome": outcome_example(
            "informational", "Test mode: nothing was stored. This would store a lab result record for the patient "
                             "it names, if that patient is registered at the hospital (test mode never says whether "
                             "a patient exists).", severity="information")}}]}},
}

# --- the read-back ----------------------------------------------------------------------------------------

READ_BACK_SCHEMA = {
    "type": "object", "title": "Stored resource", "description":
    "What Endod stored for a resource you sent: its id and version, the patient, the title and date, whether it "
    "reached the patient's Endod app, and `status` entered-in-error when it was retracted at the hospital. "
    "(Endod keeps the record it made from your resource, not your resource itself.)",
    "properties": {
        "resourceType": {"type": "string"}, "id": {"type": "string", "description": "Endod's record id."},
        "meta": {"type": "object", "properties": {"versionId": {"type": "string"},
                                                  "lastUpdated": {"type": "string", "format": "date-time"}}},
        "identifier": {"type": "array", "items": _ref("FhirIdentifier"),
                       "description": "Your id for it, when you sent one."},
        "status": {"type": "string", "description": "`entered-in-error` once retracted at the hospital; else "
                                                   "final, active, finished or current (not on a Condition)."},
        "verificationStatus": {**_ref("FhirCodeableConcept"),
                               "description": "Condition only (it has no `status`): `confirmed`, or "
                                              "`entered-in-error` once retracted at the hospital."},
        "subject": _ref("FhirSubject"),
        "text": {"type": "object", "properties": {"status": {"type": "string"}, "div": {"type": "string"}}},
        "extension": {"type": "array", "items": {"type": "object"},
                      "description": "published-to-endod (valueBoolean): the patient's Endod app has this version."},
    },
    "additionalProperties": True,
}
READ_BACK_EXAMPLE = {
    "resourceType": "Observation", "id": "5f0c1e2d3c4b5a69788796a5b4c3d2e1",
    "meta": {"versionId": "2", "lastUpdated": "2026-10-01T07:00:00+00:00"},
    "identifier": [{"system": "https://endod-health.com/integrations/endod_live_3f9a/Observation",
                    "value": "hb-000123"}],
    "status": "final", "subject": SUBJECT, "code": {"text": "Hemoglobin"},
    "effectiveDateTime": "2026-10-01T06:30:00+00:00",
    "text": {"status": "generated", "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">Hemoglobin</div>"},
    "extension": [{"url": "https://endod-health.com/fhir/StructureDefinition/published-to-endod",
                   "valueBoolean": True}],
}


def components() -> Dict[str, Any]:
    out: Dict[str, Any] = dict(copy.deepcopy(DATATYPES))
    for name, schema in RESOURCES.items():
        out[f"Fhir{name}"] = copy.deepcopy(schema)
    out["FhirPatientEntry"] = copy.deepcopy(PATIENT_ENTRY)
    out["FhirBundle"] = copy.deepcopy(BUNDLE_SCHEMA)
    out["FhirBundleResponse"] = copy.deepcopy(BUNDLE_RESPONSE_SCHEMA)
    out["FhirStoredResource"] = copy.deepcopy(READ_BACK_SCHEMA)
    return out
