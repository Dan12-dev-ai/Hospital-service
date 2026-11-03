# Endod Hospital Integration API

Connect your hospital's own system (EMR, LIS, RIS, pharmacy system) to Endod.
Your hospital keeps its own system and uses Endod as a layer: patients find and
book your hospital in the Endod app, and everything that follows is done
through this API.

- register patients (Endod issues the hospital number) and link them to their
  Endod account;
- read the in-person bookings patients make through Endod, cancel them, mark
  visits completed;
- run the doctors' queues (check in, call the next patient, done, skip);
- send lab results, prescriptions, diagnoses, visit notes, documents and imaging
  reports as FHIR R4 resources, and read them back;
- set and cancel follow-ups (the patient gets an SMS and a reminder);
- see what pharmacies gave from your prescriptions;
- keep your price list in step: the consultation price patients see, lab tests,
  imaging and procedures;
- charge patients for lab tests, imaging, procedures and other services, with
  Endod's service fee added (the patient sees the bill in the Endod app);
- get notified (webhooks) when bookings, patient links, dispensing or charges change.

<!-- Video visits (HOSPITAL_VIDEO_VISITS_ENABLED): when they return, the bookings line reads:
- read the bookings patients make through Endod, approve or decline video
  visits, cancel them, mark visits completed;
-->

- **Base URL:** `https://api.endod-health.com/hospital/v1`
- **Token URL:** `https://api.endod-health.com/hospital/v1/oauth/token`
- **Signing keys of access tokens:** `https://api.endod-health.com/hospital/v1/.well-known/jwks.json`
- **OpenAPI:** `https://api.endod-health.com/hospital/v1/openapi.json` (this guide, with every
  endpoint, its scope, request and answer with examples, and every webhook event, at `/docs`)

Only hospitals approved by Endod can connect a system; a suspended hospital's
connections stop working at once.

## 1. Connect your system (API keys)

An administrator or developer signs in to the Endod developer dashboard
(`https://hospital.endod-health.com`), opens **API keys** and clicks
**Create API key**:

1. a name (e.g. "Main lab system");
2. what it may do (each is a *scope* in this API):

   | In the dashboard | Scope | Accepts |
   |---|---|---|
   | Send lab results | `records.labs.write` | `Observation` (category `laboratory`), `DiagnosticReport` (category `LAB`) |
   | Send prescriptions | `records.prescriptions.write` | `MedicationRequest` |
   | Send diagnoses | `records.diagnoses.write` | `Condition` |
   | Send visit notes | `records.visits.write` | `Encounter` |
   | Send documents | `records.documents.write` | `DocumentReference` (PDF, JPEG, PNG or WebP, inline base64) |
   | Send imaging reports | `records.imaging.write` | `DiagnosticReport` (category `RAD`) |
   | See patients | `patients.read` | `GET /patients/{mrn}` |
   | Register and link patients | `patients.write` | `POST /patients`, `POST` and `DELETE /patients/{mrn}/link` |
   | See bookings | `bookings.read` | `GET /bookings`, `GET /bookings/{id}` |
   | Decide on bookings | `bookings.write` | `POST /bookings/{id}/cancel`, `/complete`; `GET /doctors` |
   | Set follow-ups | `followups.write` | `POST` and `GET /patients/{mrn}/follow-ups`, `POST /follow-ups/{id}/cancel`; `GET /doctors` |
   | See what pharmacies gave | `prescriptions.read` | `GET /prescriptions/{id}` |
   | Run the queue | `queue.write` | `GET /queue`, `POST /queue/check-in`, `/queue/{doctor}/call-next`, `/queue/entries/{id}/done`, `/skip`, `/cancel`; `GET /doctors` |
   | See the price list | `prices.read` | `GET /prices` |
   | Sync the price list | `prices.write` | `PUT /prices/consultation`, `/lab-tests`, `/imaging`, `/procedures`; `GET /prices` |
   | Get notified of changes | `webhooks` | events sent to your webhook URL |

   Each `records.*.write` scope also reads back what was sent with it
   (`GET /fhir/{Type}/{id}`).

   and **Live** (real records) or **Test** (everything is checked, nothing is stored);
3. the **client ID** and **client secret**, shown once. Save the secret in your
   system's secret store now: Endod keeps only a hash of it and cannot show it again
   (it can be rotated). "Download setup guide" prints the connection's details
   (never the secret).

On the key, an administrator or developer can limit the addresses the system may
call from, switch it to public-key authentication, rotate the secret and revoke
the key. **Webhooks** sets the webhook URL and its secret, sends a test event and
shows recent deliveries; **Logs** shows each key's recent requests. Every change
asks for a fresh code from the authenticator app (two-step verification) and is
audited. The dashboard's **Playground** tries any endpoint in Test mode, from the
dashboard's server, with a Test key of its own.

## 2. Authentication

OAuth 2.0 client credentials. Tokens are JWTs signed ES256 (the `kid` in their
header names the key at `/.well-known/jwks.json`), valid **5 minutes**: get a new
one when it expires (`expires_in`), not for every request.

### With the client secret (HTTP Basic, preferred)

```bash
curl -s https://api.endod-health.com/hospital/v1/oauth/token \
  -u "$CLIENT_ID:$CLIENT_SECRET" \
  -d grant_type=client_credentials \
  -d "scope=records.labs.write"
```

or with the credentials in the form (`client_secret_post`):

```bash
curl -s https://api.endod-health.com/hospital/v1/oauth/token \
  -d grant_type=client_credentials \
  -d client_id="$CLIENT_ID" --data-urlencode client_secret="$CLIENT_SECRET"
```

Node.js (18 or later):

```javascript
const basic = Buffer.from(`${process.env.CLIENT_ID}:${process.env.CLIENT_SECRET}`).toString("base64");
const res = await fetch("https://api.endod-health.com/hospital/v1/oauth/token", {
  method: "POST",
  headers: { Authorization: `Basic ${basic}`, "Content-Type": "application/x-www-form-urlencoded" },
  body: new URLSearchParams({ grant_type: "client_credentials", scope: "records.labs.write" }),
});
const { access_token: token } = await res.json();
```

Python:

```python
import os, requests
token = requests.post("https://api.endod-health.com/hospital/v1/oauth/token",
                      auth=(os.environ["CLIENT_ID"], os.environ["CLIENT_SECRET"]),
                      data={"grant_type": "client_credentials", "scope": "records.labs.write"}).json()["access_token"]
```

The answer:

```json
{"access_token": "eyJhbGciOiJFUzI1NiIs...", "token_type": "Bearer", "expires_in": 300,
 "scope": "records.labs.write"}
```

`scope` is optional (space-separated); without it the token carries every scope
granted to the connection. Asking for a scope not granted is refused (`invalid_scope`).

### With a private key (`private_key_jwt`, SMART Backend Services)

Make an EC P-256 (ES256) or RSA 2048+ (RS256) key pair, keep the private key in your
system, and paste the **public** key set (JWKS) on the key in the dashboard ("Use a
public key instead"). The secret then stops working.

Each token request carries a fresh signed assertion:

- header: `alg` ES256 or RS256, `kid` of your key;
- `iss` and `sub`: your client ID; `aud`: the token URL;
- `exp`: at most 5 minutes ahead; `jti`: unique, never reused (a replay is refused).

```python
import time, uuid, jwt, requests   # PyJWT
TOKEN_URL = "https://api.endod-health.com/hospital/v1/oauth/token"
assertion = jwt.encode({"iss": CLIENT_ID, "sub": CLIENT_ID, "aud": TOKEN_URL,
                        "exp": int(time.time()) + 240, "jti": uuid.uuid4().hex},
                       PRIVATE_KEY_PEM, algorithm="ES256", headers={"kid": "my-key-1"})
token = requests.post(TOKEN_URL, data={
    "grant_type": "client_credentials", "scope": "records.labs.write",
    "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
    "client_assertion": assertion}).json()["access_token"]
```

### Refusals

| HTTP | `error` | Why |
|---|---|---|
| 400 | `unsupported_grant_type` | `grant_type` is not `client_credentials` |
| 400 | `invalid_request` | malformed request, or two authentication methods |
| 401 | `invalid_client` | unknown or disconnected client, wrong secret, bad assertion (signature, `aud`, `exp`, reused `jti`), or a call from an address not allowed |
| 400 | `unauthorized_client` | the hospital is not approved by Endod, or is suspended |
| 400 | `invalid_scope` | a scope not granted to the connection |
| 429 | `slow_down` | too many token requests (see Limits); wait `Retry-After` seconds |

## 3. Records (FHIR R4)

```
POST /fhir                    a Bundle of type "transaction" or "batch"
POST /fhir/{ResourceType}     one resource
Authorization: Bearer <access token>
Content-Type: application/fhir+json
Idempotency-Key: <optional, your unique id for this request>
```

### Patients

Records are filed for patients **already registered at your hospital** (with
`POST /patients`, section 4): FHIR never creates a patient, and
Endod never matches by name. Name the patient in `subject` by:

- the hospital number (MRN) Endod issued, with your hospital's MRN system,
  `https://endod-health.com/hospital/<your hospital code, lower case>/mrn` (shown
  in the dashboard and in the setup guide), e.g.
  `{"identifier": {"system": "https://endod-health.com/hospital/sph/mrn", "value": "SPH-000124"}}`;
- or the patient's Endod ID: `{"identifier": {"system": "https://endod-health.com/id", "value": "DE482731"}}`;
- or a reference to a `Patient` entry of the same bundle carrying one of those identifiers
  (`"subject": {"reference": "urn:uuid:..."}`). That entry only names the patient.

An unknown patient is an error for that entry (an OperationOutcome). When both an Endod
ID and a hospital number are given, they must name the same patient; otherwise the
entry is refused (`business-rule`), never matched to one of them. A record of a
patient not linked to Endod stays at the hospital and reaches the patient's Endod
app once they are linked; for a linked patient it is published at once.

### Lab results

A lab result (`records.labs.write`):

```bash
curl -s https://api.endod-health.com/hospital/v1/fhir \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/fhir+json" \
  -H "Idempotency-Key: lis-2026-10-01-000123" \
  -d '{
  "resourceType": "Bundle", "type": "transaction",
  "entry": [{
    "request": {"method": "PUT", "url": "Observation/hb-000123"},
    "resource": {
      "resourceType": "Observation", "id": "hb-000123", "meta": {"versionId": "1"},
      "status": "final",
      "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                "code": "laboratory"}]}],
      "code": {"coding": [{"system": "http://loinc.org", "code": "718-7"}], "text": "Hemoglobin"},
      "subject": {"identifier": {"system": "https://endod-health.com/hospital/sph/mrn", "value": "SPH-000124"}},
      "effectiveDateTime": "2026-10-01T09:30:00+03:00",
      "valueQuantity": {"value": 13.2, "unit": "g/dL"},
      "referenceRange": [{"low": {"value": 12}, "high": {"value": 16}}],
      "interpretation": [{"coding": [{"code": "N"}]}]
    }
  }]}'
```

A lab panel (`records.labs.write`): a `DiagnosticReport` with category `LAB`; its
contained Observations are its tests (without them, the report's code is the test
and `conclusion` its notes).

```json
{"resourceType": "DiagnosticReport", "status": "final",
 "category": [{"coding": [{"code": "LAB"}]}], "code": {"text": "Complete blood count"},
 "subject": {"identifier": {"system": "https://endod-health.com/id", "value": "DE482731"}},
 "effectiveDateTime": "2026-10-01T09:30:00+03:00", "conclusion": "Within normal limits",
 "contained": [
   {"resourceType": "Observation", "code": {"text": "WBC"}, "valueQuantity": {"value": 6.1, "unit": "10*3/uL"}},
   {"resourceType": "Observation", "code": {"text": "Platelets"}, "valueQuantity": {"value": 250, "unit": "10*3/uL"}}
 ]}
```

### Imaging reports

An imaging report (`records.imaging.write`):

```json
{"resourceType": "DiagnosticReport", "status": "final",
 "category": [{"coding": [{"code": "RAD"}, {"code": "CT", "display": "CT"}]}],
 "code": {"text": "CT head without contrast"},
 "subject": {"identifier": {"system": "https://endod-health.com/hospital/sph/mrn", "value": "SPH-000124"}},
 "issued": "2026-10-01T11:00:00+03:00", "conclusion": "No acute intracranial bleed.",
 "conclusionCode": [{"text": "Normal study"}]}
```

### Prescriptions

A prescription (`records.prescriptions.write`):

```json
{"resourceType": "MedicationRequest", "status": "active", "intent": "order",
 "medicationCodeableConcept": {"text": "Amoxicillin 500 mg capsule"},
 "subject": {"identifier": {"system": "https://endod-health.com/hospital/sph/mrn", "value": "SPH-000124"}},
 "authoredOn": "2026-10-01", "requester": {"display": "Dr. Abebe Kebede"},
 "dosageInstruction": [{"text": "1 capsule three times a day",
   "timing": {"repeat": {"frequency": 3, "period": 1, "periodUnit": "d", "boundsDuration": {"value": 7, "unit": "days"}}},
   "route": {"text": "oral"}}],
 "dispenseRequest": {"quantity": {"value": 21, "unit": "capsules"}}}
```

### Diagnoses

A diagnosis (`records.diagnoses.write`):

```json
{"resourceType": "Condition",
 "code": {"text": "Malaria", "coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "B54"}]},
 "clinicalStatus": {"coding": [{"code": "active"}]},
 "subject": {"identifier": {"system": "https://endod-health.com/hospital/sph/mrn", "value": "SPH-000124"}},
 "recordedDate": "2026-10-01", "recorder": {"display": "Dr. Abebe Kebede"}}
```

### Visit notes

A visit note (`records.visits.write`): the reason (`reasonCode`), the diagnoses'
names (`diagnosis.condition.display`) and the discharge disposition become the note.

```json
{"resourceType": "Encounter", "status": "finished", "class": {"code": "AMB", "display": "ambulatory"},
 "type": [{"text": "Outpatient visit"}],
 "subject": {"identifier": {"system": "https://endod-health.com/hospital/sph/mrn", "value": "SPH-000124"}},
 "period": {"start": "2026-10-01T08:00:00+03:00"},
 "reasonCode": [{"text": "Fever for 3 days"}],
 "diagnosis": [{"condition": {"display": "Malaria"}}],
 "hospitalization": {"dischargeDisposition": {"text": "Home; review in 1 week"}},
 "participant": [{"individual": {"display": "Dr. Abebe Kebede"}}]}
```

### Documents

A document (`records.documents.write`): PDF, JPEG, PNG or WebP, base64 inline,
recognised by its content (not its name or declared type), at most 10 MB per request.

```json
{"resourceType": "DocumentReference", "status": "current",
 "subject": {"identifier": {"system": "https://endod-health.com/hospital/sph/mrn", "value": "SPH-000124"}},
 "description": "Discharge summary", "date": "2026-10-02T10:00:00+03:00",
 "content": [{"attachment": {"contentType": "application/pdf", "title": "discharge-summary.pdf",
                             "data": "JVBERi0xLjQK..."}}]}
```

### Answers

A bundle gets a `transaction-response` or `batch-response` Bundle, one entry per
entry sent, in order:

```json
{"resourceType": "Bundle", "type": "transaction-response",
 "entry": [{"response": {"status": "201 Created", "location": "Observation/5f0c.../_history/1", "etag": "W/\"1\""}}]}
```

- **transaction:** all or nothing. If any entry fails, nothing is stored and the
  answer is an OperationOutcome naming each failed entry (`Bundle.entry[i]`).
- **batch:** each entry on its own; a failed entry has an error status and an
  OperationOutcome in `response.outcome`.

A single resource gets `201 Created` (or `200 OK` for a correction or a repeat) with
a `Location` header, or an OperationOutcome.

`Location` is `Type/<record id>/_history/<version>`. Read back what Endod stored
with the scope you sent it with:

```bash
curl -s https://api.endod-health.com/hospital/v1/fhir/Observation/5f0c... -H "Authorization: Bearer $TOKEN"
```

by the record id, or by your own resource id (`GET /fhir/Observation/hb-000123`).
The answer is the record Endod made from your resource (not your resource itself):
its id and version (`meta.versionId`), the patient, the title and date, `status`
`entered-in-error` once it was retracted at the hospital, and the extension
`published-to-endod` (whether the patient's Endod app has this version). A record is
served only as the type it was sent as; records that reached Endod another way (the
former hospital portal, a file import) are not served here.

### Corrections and retries

- Give your resources an `id` (`PUT Type/id`) and a `meta.versionId`: sending the same
  id with a new `versionId` (or other content) **corrects** the record: a new version,
  sent again to the patient's Endod app. The
  same `versionId` again changes nothing (`200 OK`). A correction cannot move a record
  to another patient or kind (`409`).
- Without an `id`, sending exactly the same resource twice stores it once.
- Send an **`Idempotency-Key`** with each request you may retry (a timeout, a lost
  answer): the same key with the same request answers the first answer again (header
  `Idempotent-Replayed: true`) for 24 hours; the same key with another request is
  refused (`422`).

## 4. Patients (`patients.write`, `patients.read`)

Register a patient at the hospital (Endod checks the details).
Endod issues the hospital number (MRN): keep it in your system and name the
patient by it everywhere (in FHIR `subject`, and in the paths below).

```bash
curl -s https://api.endod-health.com/hospital/v1/patients \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Idempotency-Key: emr-reg-2026-10-01-0042" \
  -d '{"full_name": "Almaz Tefera", "sex": "female", "date_of_birth": "1990-04-12",
       "phone": "+251911234567", "payer": "cash", "claimed_endod_id": "DE482731"}'
```

`201` with the patient (`mrn`, e.g. `SPH-000124`). `full_name` and `sex` (`female`,
`male`) are required; `date_of_birth` or `age_years` (not both); `phone`,
`address`, `emergency_contact_name` and `_phone`, `payer` (`cash`, `cbhi`,
`private`, `credit`), `payer_number`, `full_name_am`. A patient with the same name
and phone number is refused (`409`, naming their number) unless
`"confirm_duplicate": true`. An Endod ID the patient gives is kept as a claim
(`claimed_endod_id`), never sent to Endod until the patient is linked.

`GET /patients/{mrn}` (`patients.read`) reads the patient, with `link.status`:
`not_linked`, `pending`, `linked` (records reach the patient's Endod app) or
`refused` (`link.request.reason`). Opening a patient is audited.

### Link a patient to their Endod account

By the Endod ID and the phone number on the account, or by the health card's QR.

```bash
curl -s https://api.endod-health.com/hospital/v1/patients/SPH-000124/link \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"endod_id": "DE482731", "phone": "+251911234567"}'
# or: -d '{"card_url": "https://endod-health.com/card/DE482731?s=..."}'
```

`202 Accepted` with `status: pending`: Endod checks the account and answers with
the webhook `patient.linked` or `patient.link_refused` (also in `GET
/patients/{mrn}`). Once linked, the patient's records and upcoming follow-ups are
sent to their Endod app. A patient already linked is refused (`409`: unlink
first). `DELETE /patients/{mrn}/link` unlinks (or withdraws a pending request):
nothing more is sent; webhook `patient.unlinked`.

### Enrol a patient without an Endod account (by SMS)

For a patient who has no Endod account, often no smartphone: Endod creates one
on the strength of a code texted to the patient's phone. The patient then
gets their health information by SMS: their card number (Endod ID), follow-up
and appointment texts, prescription codes for pharmacies, and "a new lab result
/ report is ready" notices (never the result itself). Later, the patient may
sign up in the Endod app with the same phone and keep the same account.

1. Ask Endod to text the code (to the patient's phone number, or `phone`):

```bash
curl -s -X POST https://api.endod-health.com/hospital/v1/patients/SPH-000124/sms-enrol \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}'
```

`202` with `status: sending`; the webhook `patient.sms_enrolment` follows with
`status: code_sent` (or `failed`: `rate_limited`, one code a minute and five an
hour per phone; `invalid_phone`; `sms_unavailable`). Only the phone number goes to
Endod at this step.

2. Ask the patient for the 6-digit code and send it (valid 10 minutes, 5 tries):

```bash
curl -s -X POST https://api.endod-health.com/hospital/v1/patients/SPH-000124/sms-enrol/verify \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"code": "482913", "language": "am"}'
```

`202` with `status: verifying`; then `patient.sms_enrolment` with `status:
enrolled` and the Endod ID (followed by `patient.linked`: the patient is linked
and their records reach Endod), or `code_sent` with `reason: wrong_code` and
`attempts_left` (ask again), or `failed` (`expired`, `too_many_attempts`: start
again at step 1; `not_allowed`: the phone's Endod account is closed). If the
phone already has an Endod account, that account is linked (no second one).
Endod texts the patient their card number and an SMS PIN. A patient who forgot
their PIN is enrolled again (steps 1 and 2): a new PIN is texted. The latest
enrolment is in `GET /patients/{mrn}` (`link.sms_enrolment`).

## 5. Bookings (`bookings.read`, `bookings.write`)

```bash
curl -s "https://api.endod-health.com/hospital/v1/bookings?status=confirmed&from=2026-10-01T00:00:00Z" \
  -H "Authorization: Bearer $TOKEN"
```

Filters: `status` (`awaiting_doctor`, `confirmed`, `rejected`, `cancelled`,
`completed`), `from` and `to` (scheduled time), `updated_since`, `limit` (at most
500). `GET /bookings/{id}` reads one. A booking carries its id, Endod's appointment
id, status, visit mode (`in_person`), service, time and duration, how the patient
pays, the price and Endod's service fee (section 10), the patient's Endod ID, name and phone, the reason it was
cancelled, and when it was decided; never the note the patient typed. Patients book
in-person visits at the consultation price you set (section 9); a booking arrives
`confirmed`.

```json
{"id": "9f0c...", "endod_appointment_id": "...", "status": "confirmed", "visit_mode": "in_person",
 "service": "general_medicine", "scheduled_at": "2026-10-02T06:30:00+00:00", "duration_minutes": 30,
 "payment": "at_hospital", "price": "150.00", "service_fee": "25.00", "total": "175.00",
 "collect_at_hospital": "175.00", "fee_owed_to_endod": "25.00", "paid_at": null, "paid_method": null,
 "patient": {"endod_id": "DE482731", "name": "...", "phone": "+251911234567"},
 "doctor": null, "reason": null, "decided_at": null, "created_at": "...", "updated_at": "..."}
```

`payment` is `online` (the patient paid Endod when booking, Endod's fee included;
Endod pays the hospital its price) or `at_hospital` (collect `collect_at_hospital`,
in birr, from the patient at the visit: the price plus Endod's service fee, which
the hospital owes Endod; then `POST /bookings/{id}/paid`, section 10).

### Decide (`bookings.write`)

Endod tells the patient and, for a booking paid online, refunds them when it is
cancelled.

| Call | Body | Does |
|---|---|---|
| `POST /bookings/{id}/cancel` | `{"reason": "..."}` | a confirmed booking is cancelled |
| `POST /bookings/{id}/complete` | none | a confirmed visit that has started is `completed` |

<!-- Video visits (HOSPITAL_VIDEO_VISITS_ENABLED; off: these two answer 404 and are not in the OpenAPI document).
When they return, the table above also has:

| `POST /bookings/{id}/approve` | `{"doctor_id": "..."}` | a video visit `awaiting_doctor` is confirmed with that doctor and a video room (`409` once its time passed) |
| `POST /bookings/{id}/decline` | `{"reason": "..."}` | a video visit `awaiting_doctor` is declined (`rejected`) |

and cancel reads "a confirmed booking is cancelled (one awaiting a doctor is declined)"; a booking carries
"the doctor of an approved video visit", and Endod refunds a booking "when it is declined or cancelled".
-->

Each answers the booking. The reason (2 to 300 characters) is told to the patient.
A decision the booking's state does not allow is `409` (e.g. "This visit is already
closed."). `GET /doctors` (`bookings.write`, `queue.write` or `followups.write`)
lists the hospital's doctors with their ids.

## 6. The queue (`queue.write`)

The doctors' queues for the day, as at the hospital's front desk:

```bash
curl -s https://api.endod-health.com/hospital/v1/queue/check-in \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"doctor_id": "c0ffee...", "patient_mrn": "SPH-000124"}'
```

Check in by a confirmed in-person booking (`booking_id`: this links the hospital
patient to Endod without asking again), a registered patient (`patient_mrn`), or
a walk-in (`"walk_in": {"name": "...", "phone": "+2519..."}`); `doctor_id` defaults
to the booking's doctor. A patient named together with a booking must already be
the booking's patient (the same confirmed or claimed Endod ID, or the same phone
number); otherwise `409`: check in by the booking alone, or link the patient first. The answer is the doctor's queue with the new `ticket`.
`POST /queue/{doctor_id}/call-next` calls the next patient (yesterday's leftovers
first; `409` while someone is still called), `POST /queue/entries/{id}/done`,
`/skip` and `/cancel` close an entry, and `GET /queue?day=&doctor_id=` reads the
board. Linked patients follow their place in the Endod app; anyone with a phone
gets an SMS when their turn is near and when they are called.

## 7. Follow-ups (`followups.write`)

```bash
curl -s https://api.endod-health.com/hospital/v1/patients/SPH-000124/follow-ups \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"date": "2026-10-15", "note": "Review the blood film result.", "doctor_id": "c0ffee..."}'
```

`date` after today and within two years (the
hospital's date), an optional `note` (at most 500 characters) shown to the patient,
an optional `doctor_id` and `booking_id`. A linked patient gets an SMS now and a
reminder before the day (a patient linked later gets it then). `GET
/patients/{mrn}/follow-ups` lists the scheduled ones; `POST /follow-ups/{id}/cancel`
cancels one (Endod is told).

## 8. Prescriptions dispensed (`prescriptions.read`)

When a pharmacy gives medicine from one of your prescriptions through Endod, the
webhook `prescription.dispensed` names it (ids and statuses only). Read the
details with the prescription's id (the record id of the `Location` of the
MedicationRequest you sent):

```json
{"id": "6e5d...", "patient": {"mrn": "SPH-000124", "endod_id": "DE482731"},
 "title": "Amoxicillin 500 mg capsule", "version": 1, "retracted": false, "status": "partly",
 "items": [{"index": 0, "drug": "Amoxicillin 500 mg capsule", "quantity": "21 capsules", "quantity_total": 21,
            "status": "partly_given", "given_total": 14, "remaining": 7,
            "last_given_at": "2026-10-01T10:15:00+00:00", "last_pharmacy": "Kenema Pharmacy No. 4"}],
 "dispenses": [{"dispense_id": "dsp_01J9", "at": "2026-10-01T10:15:00+00:00",
                "pharmacy_name": "Kenema Pharmacy No. 4", "status": "open", "items": [...]}]}
```

`status`: `not_dispensed`, `partly` or `fully`; each item `not_given`,
`partly_given` or `given`.

### Retries (`Idempotency-Key`)

Every `POST` above takes an `Idempotency-Key`, as the FHIR endpoints do: the same
key with the same request answers the first answer again for 24 hours
(`Idempotent-Replayed: true`); the same key with another request is refused (`422`).

## 9. Pricing (`prices.write`, `prices.read`)

Keep the hospital's prices in step with your system. Each call sends a whole
category and is safe to repeat: sending the same thing again changes nothing.
Prices are birr with at most two decimals (`"350.00"` or `350`), answered as text
with two decimals.

| Call | Body | Does |
|---|---|---|
| `PUT /prices/consultation` | `{"in_person": "150.00"}` | the in-person visit price patients see when they book in the Endod app (announced at once) |
| `PUT /prices/lab-tests` | `{"items": [...]}` | replaces the lab tests |
| `PUT /prices/imaging` | `{"items": [...]}` | replaces the imaging studies |
| `PUT /prices/procedures` | `{"items": [...]}` | replaces the procedures |
| `GET /prices` | none | everything (`prices.read` or `prices.write`) |

Each item is `{"code", "name", "price", "active"}`: `code` is yours (1 to 40 letters,
digits, `.`, `_`, `-`, `/`), once per list; `active: false` keeps an item listed but
not offered now. Items with a new code are added, known codes updated, and codes
not sent are removed (an empty list clears the category). At most 2000 items.

```bash
curl -s -X PUT https://api.endod-health.com/hospital/v1/prices/lab-tests \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"items": [
        {"code": "CBC", "name": "Complete blood count", "price": "350.00", "active": true},
        {"code": "MAL-RDT", "name": "Malaria rapid test", "price": "120.00", "active": true}]}'
```

Node.js:

```javascript
await fetch("https://api.endod-health.com/hospital/v1/prices/consultation", {
  method: "PUT",
  headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  body: JSON.stringify({ in_person: "150.00" }),
});
```

Python:

```python
requests.put("https://api.endod-health.com/hospital/v1/prices/imaging",
             headers={"Authorization": f"Bearer {token}"},
             json={"items": [{"code": "XR-CHEST", "name": "Chest X-ray", "price": "450.00", "active": True}]})
```

A category answers the list now and what changed:

```json
{"currency": "ETB", "category": "lab_tests",
 "items": [{"code": "CBC", "name": "Complete blood count", "price": "350.00", "active": true,
            "updated_at": "2026-11-03T08:00:00+00:00"}],
 "added": 1, "updated": 0, "removed": 0, "unchanged": 0}
```

`PUT /prices/consultation` answers `{"currency": "ETB", "in_person": "150.00",
"listed": true}`: `listed` says whether patients can find and book the hospital
(it also needs its location, set in the dashboard's Settings). A code twice in a
list, or a price with more than two decimals, is refused (`422`). Changes are
audited with the key.

## 10. Charges (`charges.write`, `charges.read`)

Endod covers the cost of SMS and earns a **service fee, paid by the patient**
(never by the hospital), on every payment the patient makes for a hospital service:
a booking, a lab test, imaging, a procedure, anything else. Charge patients through
Endod and Endod adds its fee: a 200 birr bill becomes 225 birr (with the fee at 25
birr); a second test, the same again.

**The rule.** One fee per charge (however many items it has) and per paid booking:
`fee = flat + percent of the subtotal`, rounded half up to the santim; no fee on
0. Endod sets the fee (it may change); `GET /service-fee` answers the fee in force
(`charges.read`, `charges.write` or `bookings.read`). Every charge keeps the fee it
was made with (`fee.version`).

```json
{"currency": "ETB", "enabled": true, "flat": "25.00", "percent": "0.00",
 "rule": "one fee per charge or booking: flat + percent of the subtotal, rounded to the santim; none on 0",
 "example": {"subtotal": "200.00", "service_fee": "25.00", "total": "225.00"},
 "updated_at": "2026-11-03T08:00:00+00:00"}
```

| Call | Body | Does |
|---|---|---|
| `POST /charges` | `{"mrn", "items": [...], "booking_id"?}` | a charge: Endod answers the subtotal, its fee and the total |
| `POST /charges/{id}/paid` | `{"method", "reference"?, "paid_at"?}` | the patient paid the hospital the total |
| `POST /charges/{id}/void` | `{"reason"}` | an open charge is cancelled |
| `GET /charges` | `status`, `mrn`, `from`, `to`, `limit` | charges, newest first (`charges.read` or `charges.write`) |
| `GET /charges/{id}` | none | one charge with its items |
| `POST /bookings/{id}/paid` | `{"method", "reference"?, "paid_at"?}` | a visit booked through Endod and paid at the hospital was paid (`bookings.write`) |

Each item is `{"category", "code"?, "name", "amount", "quantity"}`: `category` is
`lab_test`, `imaging`, `procedure`, `consultation` or `other`; `code` is yours (e.g.
from your price list, section 9; not checked against it); `name` is what the patient
reads on the bill in the Endod app; `amount` is the price of one in birr (at most two
decimals, more than 0); `quantity` 1 to 1000 (default 1). 1 to 100 items. A
`booking_id` must be this patient's booking (else `409`).

```bash
curl -s -X POST https://api.endod-health.com/hospital/v1/charges \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Idempotency-Key: lab-order-77812" \
  -d '{"mrn": "SPH-000124", "items": [
        {"category": "lab_test", "code": "CBC", "name": "Complete blood count", "amount": "350.00", "quantity": 1},
        {"category": "imaging", "code": "XR-CHEST", "name": "Chest X-ray", "amount": "450.00", "quantity": 1}]}'
```

`201`:

```json
{"id": "3c2b...", "mrn": "SPH-000124", "patient_id": "5f0c...", "endod_id": "DE482731", "booking_id": null,
 "items": [{"category": "lab_test", "code": "CBC", "name": "Complete blood count", "amount": "350.00",
            "quantity": 1, "line_total": "350.00"},
           {"category": "imaging", "code": "XR-CHEST", "name": "Chest X-ray", "amount": "450.00",
            "quantity": 1, "line_total": "450.00"}],
 "currency": "ETB", "subtotal": "800.00", "service_fee": "25.00", "total": "825.00",
 "fee": {"version": 3, "flat": "25.00", "percent": "0.00"}, "status": "open", "method": null,
 "reference": null, "paid_at": null, "void_reason": null, "voided_at": null, "fee_owed_to_endod": null,
 "created_at": "...", "updated_at": "..."}
```

Collect `total` from the patient. A patient linked to Endod sees the bill in the
Endod app and gets an SMS with the amounts only ("your bill at the hospital is ETB
825.00 (incl. Endod service fee ETB 25.00)"): never what it is for. When the patient
has paid:

```bash
curl -s -X POST https://api.endod-health.com/hospital/v1/charges/3c2b.../paid \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"method": "mobile_money", "reference": "TB7781234"}'
```

`method` is `cash`, `card`, `mobile_money` or `other`; `paid_at` (with its offset)
defaults to now and cannot be in the future. The answer has `"status": "paid"` and
`fee_owed_to_endod`: the hospital collected Endod's fee with the total and owes it to
Endod (Endod settles fees with the hospital). Sending it again the same way changes
nothing; a voided charge cannot be paid and a paid one cannot be voided (`409`).
Online payment of charges is not offered yet: patients pay at the hospital.

**Bookings.** A booking paid at the hospital (`payment: at_hospital`, section 5)
carries Endod's fee too: collect `collect_at_hospital` (the price plus
`service_fee`); `fee_owed_to_endod` is Endod's. Say when it was paid with `POST
/bookings/{id}/paid` (a confirmed or completed visit); a visit completed without it
counts as paid when completed. A booking paid online (`payment: online`) was paid
to Endod already. A free visit has no fee.

Python:

```python
created = requests.post(f"{BASE}/charges", headers={"Authorization": f"Bearer {token}",
                                                    "Idempotency-Key": order_id},
                        json={"mrn": mrn, "items": [{"category": "procedure", "name": "Wound dressing",
                                                     "amount": "120", "quantity": 2}]}).json()
print("Collect", created["total"], "birr (Endod fee", created["service_fee"], ")")
requests.post(f"{BASE}/charges/{created['id']}/paid", headers={"Authorization": f"Bearer {token}"},
              json={"method": "cash", "reference": receipt_number})
```

Charges are audited with the key; their items are encrypted at rest, and never in a
webhook or an SMS.

## 11. Webhooks (`webhooks`)

Endod POSTs JSON events to your webhook URL (https only, a public address):

| Event | When |
|---|---|
| `booking.created` | a patient booked a visit |
| `booking.confirmed` | an in-person booking arrived (confirmed at once) |
| `booking.cancelled` | the patient, the hospital or Endod cancelled (`data.status` says which) |
| `patient.linked` | Endod confirmed a link request, or a booking's check-in linked the patient |
| `patient.link_refused` | Endod refused a link request (`data.reason`: `not_found`, `not_verified`, `already_linked`, ...) |
| `patient.unlinked` | a patient was unlinked |
| `patient.sms_enrolment` | an enrolment by SMS moved on (`data.status`: `code_sent`, `enrolled`, `failed`; `data.reason`, `data.attempts_left`) |
| `prescription.dispensed` | a pharmacy gave medicine from one of your prescriptions |
| `charge.created` | a charge was made (the subtotal, Endod's fee, the total) |
| `charge.paid` | a charge was paid at the hospital (the hospital owes Endod the fee) |
| `charge.voided` | an open charge was voided |
| `endpoint.test` | "Send test event" in the dashboard |

<!-- Video visits (HOSPITAL_VIDEO_VISITS_ENABLED): when they return, `booking.confirmed` is also sent when
"a doctor approved a video visit", and `booking.cancelled` when "a video visit was declined". -->

```json
{"id": "evt_8c1f...", "type": "booking.confirmed", "created": "2026-10-01T06:00:00+00:00",
 "hospital_id": "...", "mode": "live",
 "data": {"booking_id": "...", "endod_appointment_id": "...", "status": "confirmed", "visit_mode": "in_person",
          "service": "general_medicine", "scheduled_at": "2026-10-02T06:30:00+00:00", "duration_minutes": 30,
          "patient": {"endod_id": "DE482731"}}}
```

Patient events carry `{"patient_id", "mrn", "endod_id"}`, with `request_id` (the
link request answered; null when a booking's check-in linked the patient) for
`patient.linked` and `patient.link_refused`, and `reason` for the refusal.
`prescription.dispensed` carries `{"prescription_id", "dispense_id",
"dispense_status": "open"|"completed", "dispensing_status": "partly"|"fully",
"dispensed_at", "patient": {"patient_id", "mrn", "endod_id"}}`, never a drug or an
amount. Charge events carry `{"charge_id", "patient_id", "mrn", "endod_id", "booking_id",
"status", "currency", "subtotal", "service_fee", "total", "method", "paid_at"}`, never
the items. The OpenAPI document (`webhooks`) has every event's payload and an example.

Events are thin (ids, statuses, times): fetch the booking with `bookings.read`, the
patient with `patients.read`, the prescription with `prescriptions.read` for the rest. Answer any **2xx** within 10 seconds. Anything else, a timeout or a redirect
(never followed) is retried with backoff (1 min, 5 min, 15 min, 30 min, 1 h, 2 h,
4 h, then every 6 h) for up to **24 hours**; then the event is dropped. Events can
arrive more than once and out of order: use `id` to skip repeats.

### Verify the signature

Every event has `Endod-Signature: t=<unix time>,v1=<hex>`, where `<hex>` is the
HMAC-SHA256 of `"<t>.<raw body>"` under your webhook secret (`whsec_...`, shown once
in the dashboard). Compare in constant time, against the **raw** body, and refuse
events older than 5 minutes.

Python:

```python
import hashlib, hmac, time

def verify(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        t = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs(time.time() - t) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", ""))
```

Node.js:

```javascript
const crypto = require("crypto");

function verify(secret, header, rawBody, tolerance = 300) {
  const parts = Object.fromEntries(header.split(",").map((p) => p.split("=", 2)));
  const t = Number.parseInt(parts.t, 10);
  if (!Number.isFinite(t) || Math.abs(Date.now() / 1000 - t) > tolerance) return false;
  const expected = crypto.createHmac("sha256", secret).update(`${t}.`).update(rawBody).digest("hex");
  const given = Buffer.from(parts.v1 || "", "utf8");
  const wanted = Buffer.from(expected, "utf8");
  return given.length === wanted.length && crypto.timingSafeEqual(given, wanted);
}
// Express: app.post("/endod", express.raw({ type: "application/json" }),
//   (req, res) => verify(SECRET, req.get("Endod-Signature"), req.body) ? res.sendStatus(204) : res.sendStatus(400));
```

C#:

```csharp
using System.Security.Cryptography;
using System.Text;

static bool Verify(string secret, string header, byte[] rawBody, int tolerance = 300)
{
    var parts = header.Split(',').Select(p => p.Split('=', 2)).Where(p => p.Length == 2)
                      .ToDictionary(p => p[0], p => p[1]);
    if (!parts.TryGetValue("t", out var ts) || !long.TryParse(ts, out var t)) return false;
    if (Math.Abs(DateTimeOffset.UtcNow.ToUnixTimeSeconds() - t) > tolerance) return false;
    using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(secret));
    var signed = Encoding.UTF8.GetBytes($"{t}.").Concat(rawBody).ToArray();
    var expected = Convert.ToHexString(hmac.ComputeHash(signed)).ToLowerInvariant();
    return parts.TryGetValue("v1", out var v1) &&
           CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(expected), Encoding.UTF8.GetBytes(v1));
}
```

## 12. Errors

Everything but the token endpoint answers errors as a FHIR OperationOutcome:

```json
{"resourceType": "OperationOutcome",
 "issue": [{"severity": "error", "code": "not-found", "diagnostics": "Unknown patient: ...",
            "expression": ["Bundle.entry[0]"]}]}
```

| HTTP | When |
|---|---|
| 400 | malformed JSON or Bundle, an unsupported resource type, a bad id |
| 401 | no token, an invalid or expired token, a disconnected client, or credentials changed since the token was issued (`WWW-Authenticate: Bearer error="invalid_token"`) |
| 403 | a scope not granted (`insufficient_scope`), a call from an address not allowed, or a hospital not approved or suspended |
| 404 | not found (another hospital's patient, booking, prescription or record is never visible) |
| 409 | a conflicting correction, a change the current state does not allow (a booking already closed, a patient already linked or registered, someone still called), or the same request processed at the same moment (send it again) |
| 413 | more than 100 entries, or more than 10 MB |
| 415 | not `application/fhir+json` (or `application/json`) |
| 422 | a resource or a field that cannot be used (unknown patient, missing date, wrong document type, a reason too short, ...) or an Idempotency-Key reused for another request |
| 429 | too many requests: wait `Retry-After` seconds |
| 503 | the API is not available |

## 13. Limits

- A bundle: at most **100 entries** and **10 MB**.
- **60 requests per minute** per connection (token requests not counted).
- Token requests: 20 per minute per client from one address, 30 per minute per address,
  and a limit for everyone together. Failed authentications slow down that address and
  that client's failed attempts (the right credentials always work).
- Access tokens live 5 minutes; client assertions at most 5 minutes.
- Dates in the future are refused; a date without a time is midnight at the hospital,
  a time without an offset is the hospital's time.

## 14. Test mode

A **Test** connection (client ID `endod_test_...`) checks and maps everything as Live
does (structure, scopes, dates, documents, how the patient is named) and answers what
WOULD be stored (each entry's `outcome` says so; the response is tagged `test-mode`).
It stores nothing, publishes nothing and changes nothing, and it never touches real
patients' data:

- it never looks a patient up: the answer is the same whether the hospital number or
  Endod ID belongs to a registered patient or not (and never contains a hospital number);
- `GET /bookings` answers made-up sample bookings (marked `"sample": true`), and
  cancel and complete are tried on them with the real rules (nothing changes,
  nothing is sent); a real booking is "not found";
- patients, follow-ups, prescriptions and the queue are checked as in Live
  (dates, Endod IDs, cards, doctors) and answer made-up data (`"sample": true`):
  `POST /patients` answers the hospital number `TEST-000001`, `GET /patients/{mrn}`
  the same made-up patient whatever the number, `GET /prescriptions/sample-prescription-1`
  a made-up prescription, and the queue the hospital's doctors each with a made-up
  patient (`sample-entry-<doctor id>`);
- enrolment by SMS is checked and answers a made-up enrolment (`sms-enrol`: `sending`;
  `verify`: `verifying`, or with the code `000000` a wrong code): no SMS is sent;
- prices are checked as in Live and answered back; nothing is written or announced,
  and `GET /prices` answers a made-up price list (`"sample": true`);
- charges are checked as in Live and answered with the real fee, as the made-up
  charge `sample-charge-1` (`"sample": true`), which can be marked paid or voided;
  nothing is stored, sent or texted; `POST /bookings/{id}/paid` is tried on the
  sample bookings;
- `GET /fhir/{Type}/{id}` is always "not found" (nothing was stored);
- its webhook receives only `endpoint.test` ("Send test event"), never a real event.

Use it while you build (the dashboard's Playground always does); create a Live
key when you are ready.

## 15. What Endod keeps

- Records are encrypted at rest, kept apart per hospital by the database, and
  published to the patient's Endod app only when the patient is linked.
- Every write is audited with the key, the action and the record ids (never a
  clinical value); so is opening a patient or a prescription.
- The request log keeps method, path, status, connection, time, duration and address
  for 30 days; never a body or a query string.
- Webhook deliveries keep status and attempts; an event's body is deleted once it is
  delivered or given up.
- Client secrets are 288-bit random values kept only as a keyed hash (HMAC-SHA256);
  webhook secrets are encrypted at rest.
