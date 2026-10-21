# Importing records from a hospital's own system

Admins and records staff import past records on the portal's **Import** page.
The file is either a **FHIR R4 Bundle** (JSON) or a **CSV** in the template
below. Every import is previewed first: the page lists what will be imported
and what will be skipped, with the reason, and nothing is saved until the
preview is confirmed. Each imported item becomes a clinical record with
`source: "import"`, published to Endod like any other record
([history-events.md](history-events.md), section 6).

Limits: a file of at most **10 MB** and at most **500** entries or rows. A
preview must be confirmed within 24 hours.

## Which patient

Records are imported only for patients **linked to Endod**. A patient is
found by:

- the hospital number (MRN), e.g. `SPH-000124`; or
- the Endod identifier `{"system": "https://endod-health.com/id", "value": "DE123456"}`
  (in the CSV, the `endod_id` column).

An item whose patient is not found, or not linked, is skipped. An item already
imported (same patient, category, title and date) is skipped too, so a file can
be imported again safely.

## FHIR R4 Bundle

A `Bundle` (any type) whose entries hold the resources below. The patient is the
resource's `subject`: a reference to a `Patient` entry of the bundle (by
`fullUrl` or `Patient/<id>`, its `identifier` list giving the MRN or Endod ID),
or an inline `identifier`.

| Resource | Becomes | Mapping |
| --- | --- | --- |
| `Condition` | diagnosis | `code` (text or display) is the condition; an ICD-10 coding's code is `code`; `clinicalStatus` gives active/resolved; date: `onsetDateTime`, `onsetPeriod.start` or `recordedDate`; `recorder` names the clinician |
| `MedicationRequest`, `MedicationStatement` | prescription | the medication's text; dose from `doseAndRate.doseQuantity` (or the dosage text), route, timing, `dispenseRequest` quantity and supply duration; date: `authoredOn`, `effectiveDateTime` or `dateAsserted` |
| `Observation` with category `laboratory` | lab_result | `code` is the test; `valueQuantity` (value and unit), `valueString`, `valueCodeableConcept`; `referenceRange`; `interpretation` L/N/H → low/normal/high, LL/HH → critical; date: `effectiveDateTime` or `issued` |
| `DiagnosticReport` with an imaging category (`RAD`, `imaging`, `radiology`) | imaging | `code` is the title; the other category coding is the modality; `conclusion` the findings |
| `DocumentReference` with an inline attachment (`content[0].attachment.data`, base64) | document | PDF, JPEG, PNG or WebP (checked by content), at most 20 MB; `description` is the title |

Other resources (Encounter, Practitioner, vital-sign Observations, documents
given only by URL, ...) are listed as skipped. A date alone (`2025-03-01`) is
read as midnight at the hospital.

## CSV

UTF-8, one record per row, with this header (the portal's Import page offers it
as a download, `import-template.csv`):

```
mrn,endod_id,category,title,occurred_at,recorded_by,condition,icd10_code,status,drug,dose,route,frequency,duration,quantity,test,value,unit,reference_range,flag,specimen,modality,body_part,findings,impression,complaint,plan,notes
```

| Column | Used for |
| --- | --- |
| `mrn` or `endod_id` | the patient (one of them is required) |
| `category` | `diagnosis`, `prescription`, `lab_result`, `imaging` or `visit_note` (documents come in FHIR bundles) |
| `title` | the record's title; if empty: the condition, "Prescription: <drug>", the test, the modality or "Visit note" |
| `occurred_at` | `YYYY-MM-DD` (midnight at the hospital) or a date and time, with its offset (`2025-01-05T10:00:00+03:00`) |
| `recorded_by` | the clinician's name, shown to the patient |
| `condition`, `icd10_code`, `status` | diagnosis (`status`: active, resolved or chronic; default active) |
| `drug`, `dose`, `route`, `frequency`, `duration`, `quantity` | prescription (one medicine per row) |
| `test`, `value`, `unit`, `reference_range`, `flag`, `specimen` | lab result (one test per row; `flag`: low, normal, high or critical) |
| `modality`, `body_part`, `findings`, `impression` | imaging |
| `complaint`, `findings`, `plan` | visit note |
| `notes` | diagnosis, prescription and lab notes |

Columns that do not apply to a row's category are ignored. Example:

```
mrn,endod_id,category,title,occurred_at,recorded_by,condition,icd10_code,status,drug,dose,route,frequency,duration,quantity,test,value,unit,reference_range,flag,specimen,modality,body_part,findings,impression,complaint,plan,notes
SPH-000124,,diagnosis,Hypertension,2025-01-05,Dr. Hana Bekele,Essential hypertension,I10,chronic,,,,,,,,,,,,,,,,,,,
,DE482731,lab_result,Malaria RDT,2025-01-05T10:00:00+03:00,Lab,,,,,,,,,,Malaria RDT,positive,,,high,blood,,,,,,,
```

## Limits and repeats

- A file is at most 10 MB; a bundle at most 500 entries, a CSV at most 500 rows.
- A CSV field is at most 65,536 characters; JSON may nest at most 64 levels.
  A file over these limits, or one that cannot be read, is refused with a
  message (HTTP 400); nothing is saved.
- Each item (a FHIR resource, a CSV row) is identified by a hash of its
  content. An item already imported at this hospital is skipped ("already
  imported"), in the preview and again when confirming, so importing the
  same file twice, or confirming two previews of it, creates each record
  once. A retracted record may be imported again.
