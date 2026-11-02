"""Request and response models of the integration API's JSON endpoints, and
the payloads of the webhook events, with the examples shown in the OpenAPI
document (``/openapi.json``, ``/docs``).

Request models reuse the portal's models (app/api/*), so a field is checked
the same way whichever way it arrives; only the names the API shows differ
(``endod_id`` where the portal says ``dedan_id``). Response models document
what the endpoints answer.
"""

from __future__ import annotations

from datetime import date
from datetime import date as Day
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.history import LinkBody
from app.api.patients import PatientCreate
from app.api.queue import WalkIn
from app.validation import Name, OptionalDedanId, OptionalPhone, OptionalText


def _examples(*examples: Dict[str, Any]) -> ConfigDict:
    return ConfigDict(json_schema_extra={"examples": list(examples)})


# --- errors -----------------------------------------------------------------------------------------

class Issue(BaseModel):
    severity: Literal["fatal", "error", "warning", "information"]
    code: str = Field(description="FHIR issue type, e.g. invalid, not-found, forbidden, security, conflict, "
                                  "too-costly, throttled, business-rule, processing.")
    diagnostics: str = Field(description="What went wrong, in plain words (at most 500 characters).")
    expression: Optional[List[str]] = Field(default=None, description="Where, e.g. Bundle.entry[2].")


class OperationOutcome(BaseModel):
    """Every error except the token endpoint's (and the informational answer to a single FHIR resource)."""

    model_config = _examples({"resourceType": "OperationOutcome", "issue": [
        {"severity": "error", "code": "not-found", "diagnostics": "Patient not found."}]})
    resourceType: Literal["OperationOutcome"]
    issue: List[Issue] = Field(min_length=1)


class OAuthErrorBody(BaseModel):
    """The token endpoint's errors (RFC 6749)."""

    model_config = _examples({"error": "invalid_client", "error_description": "Client authentication failed."})
    error: Literal["invalid_request", "invalid_client", "invalid_grant", "unauthorized_client",
                   "unsupported_grant_type", "invalid_scope", "slow_down"]
    error_description: str


# --- authentication -----------------------------------------------------------------------------------

class TokenResponse(BaseModel):
    model_config = _examples({"access_token": "eyJhbGciOiJFUzI1NiIsImtpZCI6Ii4uLiJ9.eyJ...", "token_type": "Bearer",
                              "expires_in": 300, "scope": "records.labs.write bookings.read"})
    access_token: str = Field(description="A JWT signed ES256; send it as `Authorization: Bearer <token>`.")
    token_type: Literal["Bearer"]
    expires_in: int = Field(description="Seconds the token is valid (300).")
    scope: str = Field(description="The scopes the token carries, space-separated.")


class Jwk(BaseModel):
    model_config = ConfigDict(extra="allow")
    kty: str
    kid: str
    alg: str
    use: Optional[str] = None


class Jwks(BaseModel):
    model_config = _examples({"keys": [{"kty": "EC", "crv": "P-256", "kid": "2026-10-a", "alg": "ES256",
                                        "use": "sig", "x": "f83OJ3D2xF1Bg8vub9tLe1gHMzV76e8Tus9uPHvRVEU",
                                        "y": "x_FEzRu9m36HLN_tue659LNpXW6pCyStikYjKIWI5a0"}]})
    keys: List[Jwk]


# --- patients -----------------------------------------------------------------------------------------

REGISTRATION_EXAMPLE = {
    "full_name": "Almaz Tefera", "full_name_am": "አልማዝ ተፈራ", "sex": "female", "date_of_birth": "1990-04-12",
    "phone": "+251911234567", "address": "Addis Ababa, Bole", "emergency_contact_name": "Tefera Bekele",
    "emergency_contact_phone": "+251911765432", "payer": "cash", "claimed_endod_id": "DE482731",
}


class PatientRegistration(PatientCreate):
    """A patient to register at the hospital: the portal's registration form,
    checked by the same rules. Endod gives the hospital number (MRN)."""

    model_config = ConfigDict(populate_by_name=True, json_schema_extra={"examples": [REGISTRATION_EXAMPLE]})
    full_name: Name = Field(max_length=120, description="The patient's name (2 to 120 characters).")
    sex: str = Field(description="One of `female`, `male`.", examples=["female"])
    date_of_birth: Optional[date] = Field(default=None, description="Give this or `age_years`, not both. "
                                                                      "Not in the future (hospital's date).")
    age_years: Optional[int] = Field(default=None, ge=0, le=130, description="When the date of birth is not known "
                                                                             "(it is then estimated).")
    payer: str = Field(default="cash", description="How the patient pays: `cash`, `cbhi` (community-based "
                                                   "health insurance), `private` (insurance) or `credit`.")
    claimed_dedan_id: OptionalDedanId = Field(
        default=None, alias="claimed_endod_id",
        description="An Endod ID the patient gave. Kept as a claim and never sent to Endod: link the patient "
                    "(POST /patients/{mrn}/link) to confirm it.")
    confirm_duplicate: bool = Field(default=False, description="Register even though a patient with the same "
                                                               "name and phone number is registered (409 otherwise).")


class LinkRequestBody(LinkBody):
    """By the health card's QR (`card_url`), or by the Endod ID and the phone
    number on the Endod account: the same check as the portal."""

    model_config = ConfigDict(populate_by_name=True, json_schema_extra={"examples": [
        {"endod_id": "DE482731", "phone": "+251911234567"},
        {"card_url": "https://endod-health.com/card/DE482731?s=Q2FyZFNpZ25hdHVyZS4uLg"}]})
    card_url: OptionalText = Field(default=None, max_length=700,
                                   description="The health card's QR: https://endod-health.com/card/<ID>?s=...")
    dedan_id: OptionalText = Field(default=None, max_length=16, alias="endod_id",
                                   description="The patient's Endod ID, e.g. DE482731 (with `phone`).")
    phone: OptionalPhone = Field(default=None, description="The phone number on the Endod account (with `endod_id`).")


class LinkRequestOut(BaseModel):
    id: str = Field(description="The link request's id (named again in the patient.linked or "
                                "patient.link_refused event).")
    endod_id: str
    method: Literal["card", "phone"]
    status: Literal["pending", "linked", "refused", "superseded"]
    reason: Optional[str] = Field(default=None, description="Why it was refused (e.g. `not_found`, "
                                                            "`not_verified`, `already_linked`) or superseded.")
    created_at: str
    decided_at: Optional[str] = None


class LinkOut(BaseModel):
    """Where the patient's link to Endod stands."""

    model_config = _examples({"status": "pending", "endod_id": None, "claimed_endod_id": "DE482731", "request": {
        "id": "8b7c0f3e6a1d4c55b2e9f0a1c3d5e7f9", "endod_id": "DE482731", "method": "phone", "status": "pending",
        "reason": None, "created_at": "2026-10-01T06:00:00+00:00", "decided_at": None}})
    status: Literal["not_linked", "pending", "linked", "refused"] = Field(
        description="`linked`: records reach the patient's Endod app; `pending`: Endod is checking; `refused`: the "
                    "last request was refused (see request.reason); `not_linked`: never asked, or unlinked.")
    endod_id: Optional[str] = Field(description="The confirmed Endod ID (only once linked).")
    claimed_endod_id: Optional[str] = Field(description="An Endod ID the patient gave, not confirmed.")
    request: Optional[LinkRequestOut] = Field(description="The latest link request, if any.")
    sample: Optional[bool] = Field(default=None, description="Test connections only: a made-up answer.")


PATIENT_EXAMPLE = {
    "id": "5f0c1e2d3c4b5a69788796a5b4c3d2e1", "mrn": "SPH-000124", "full_name": "Almaz Tefera",
    "full_name_am": "አልማዝ ተፈራ", "sex": "female", "date_of_birth": "1990-04-12", "dob_estimated": False,
    "age_years": 36, "phone": "+251911234567", "address": "Addis Ababa, Bole",
    "emergency_contact": {"name": "Tefera Bekele", "phone": "+251911765432"}, "payer": "cash",
    "payer_number": None, "status": "opd", "created_at": "2026-10-01T06:00:00+00:00",
    "link": {"status": "not_linked", "endod_id": None, "claimed_endod_id": "DE482731", "request": None},
}


class EmergencyContact(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None


class PatientOut(BaseModel):
    """A patient registered at the hospital."""

    model_config = _examples(PATIENT_EXAMPLE)
    id: str = Field(description="Endod's id of the patient at this hospital.")
    mrn: str = Field(description="The hospital number Endod issued, e.g. SPH-000124; name the patient by it.")
    full_name: str
    full_name_am: Optional[str] = None
    sex: str
    date_of_birth: Optional[str] = None
    dob_estimated: bool = Field(description="True when the date of birth was estimated from an age.")
    age_years: Optional[int] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    emergency_contact: EmergencyContact
    payer: str
    payer_number: Optional[str] = None
    status: str = Field(description="Where the patient is in their care (as in the portal): `opd`, `emergency`, "
                                    "`admitted`, `discharge` (cleared to go home) or `discharged`.")
    created_at: str
    link: LinkOut
    sample: Optional[bool] = Field(default=None, description="Test connections only: a made-up answer.")


# --- bookings ------------------------------------------------------------------------------------------

BOOKING_EXAMPLE = {
    "id": "9f0c2b7a1e4d4f6a8b3c5d7e9f1a2b4c", "endod_appointment_id": "apt_7d1c9e", "status": "confirmed",
    "visit_mode": "video", "service": "general_medicine", "scheduled_at": "2026-10-02T06:30:00+00:00",
    "duration_minutes": 30, "payment": "online", "price": "150.00",
    "patient": {"endod_id": "DE482731", "name": "Almaz Tefera", "phone": "+251911234567"},
    "doctor": {"id": "c0ffee00c0ffee00c0ffee00c0ffee00", "full_name": "Dr. Abebe Kebede"},
    "reason": None, "decided_at": "2026-10-01T07:10:00+00:00", "created_at": "2026-10-01T06:00:00+00:00",
    "updated_at": "2026-10-01T07:10:00+00:00",
}


class BookingPatient(BaseModel):
    endod_id: Optional[str]
    name: Optional[str]
    phone: Optional[str]


class DoctorRef(BaseModel):
    id: str
    full_name: str


class BookingOut(BaseModel):
    """A booking a patient made through Endod. Never the note the patient typed."""

    model_config = _examples(BOOKING_EXAMPLE)
    id: str = Field(description="The booking's id at the hospital.")
    endod_appointment_id: str = Field(description="Endod's appointment id.")
    status: Literal["awaiting_doctor", "confirmed", "rejected", "cancelled", "completed"] = Field(
        description="`awaiting_doctor`: a video visit waiting for a doctor's approval; `confirmed`; `rejected`: a "
                    "video visit declined; `cancelled`: by the patient, the hospital or Endod; `completed`.")
    visit_mode: Literal["in_person", "video"]
    service: Optional[str] = None
    scheduled_at: str
    duration_minutes: int
    payment: Literal["online", "at_hospital"] = Field(
        description="`online`: paid to Endod when booking (Endod pays the hospital); `at_hospital`: collect "
                    "`price` at the visit.")
    price: str = Field(description="Birr, two decimals.")
    patient: BookingPatient
    doctor: Optional[DoctorRef] = Field(default=None, description="The doctor of an approved video visit.")
    reason: Optional[str] = Field(default=None, description="Why it was declined or cancelled.")
    decided_at: Optional[str] = None
    created_at: str
    updated_at: str
    sample: Optional[bool] = Field(default=None, description="Test connections only: a made-up booking.")


class BookingList(BaseModel):
    model_config = _examples({"items": [BOOKING_EXAMPLE]})
    items: List[BookingOut]


class ApproveBody(BaseModel):
    """Approve a video visit awaiting a doctor: the doctor becomes its doctor and a video room is opened."""

    model_config = _examples({"doctor_id": "c0ffee00c0ffee00c0ffee00c0ffee00"})
    doctor_id: str = Field(min_length=1, max_length=32, description="An active doctor of the hospital "
                                                                    "(GET /doctors).")


class ReasonBody(BaseModel):
    model_config = _examples({"reason": "The doctor is away that day; please book another day."})
    reason: Name = Field(max_length=300, description="Told to the patient (2 to 300 characters).")


class DoctorOut(BaseModel):
    id: str
    full_name: str
    full_name_am: Optional[str] = None
    department: Optional[str] = Field(default=None, description="The doctor's department, if set.")


class DoctorList(BaseModel):
    model_config = _examples({"items": [{"id": "c0ffee00c0ffee00c0ffee00c0ffee00", "full_name": "Dr. Abebe Kebede",
                                         "full_name_am": None, "department": "Internal medicine"}]})
    items: List[DoctorOut]


# --- follow-ups -----------------------------------------------------------------------------------------

class FollowUpCreate(BaseModel):
    """A follow-up date for the patient, as a doctor sets one in the portal: a
    linked patient gets an SMS now and a reminder before the day."""

    model_config = _examples({"date": "2026-10-15", "note": "Review the blood film result.",
                              "doctor_id": "c0ffee00c0ffee00c0ffee00c0ffee00"})
    date: Day = Field(description="After today and within two years (the hospital's date).")
    note: OptionalText = Field(default=None, max_length=500, description="Shown to the patient with the date.")
    doctor_id: OptionalText = Field(default=None, max_length=32, description="The doctor (GET /doctors), if any.")
    booking_id: OptionalText = Field(default=None, max_length=32, description="The booking this visit came from, "
                                                                              "if any.")


FOLLOW_UP_EXAMPLE = {
    "id": "a1b2c3d4e5f60718293a4b5c6d7e8f90", "patient": {"mrn": "SPH-000124", "endod_id": "DE482731"},
    "date": "2026-10-15", "note": "Review the blood film result.", "status": "scheduled",
    "doctor": {"id": "c0ffee00c0ffee00c0ffee00c0ffee00", "full_name": "Dr. Abebe Kebede"}, "booking_id": None,
    "sent_to_endod": True, "created_at": "2026-10-01T09:00:00+00:00",
}


class FollowUpPatient(BaseModel):
    mrn: str
    endod_id: Optional[str]


class FollowUpOut(BaseModel):
    model_config = _examples(FOLLOW_UP_EXAMPLE)
    id: str = Field(description="The follow-up's id (the visit it belongs to).")
    patient: FollowUpPatient
    date: Optional[str] = Field(description="Null once cancelled.")
    note: Optional[str] = None
    status: Literal["scheduled", "cancelled"]
    doctor: Optional[DoctorRef] = None
    booking_id: Optional[str] = None
    sent_to_endod: bool = Field(description="The patient's Endod app has it (linked patients only).")
    created_at: str
    sample: Optional[bool] = None


class FollowUpList(BaseModel):
    model_config = _examples({"items": [FOLLOW_UP_EXAMPLE]})
    items: List[FollowUpOut]


# --- prescriptions -------------------------------------------------------------------------------------

PRESCRIPTION_EXAMPLE = {
    "id": "6e5d4c3b2a1908f7e6d5c4b3a2918070", "patient": {"mrn": "SPH-000124", "endod_id": "DE482731"},
    "title": "Amoxicillin 500 mg capsule", "version": 1, "retracted": False, "status": "partly",
    "items": [{"index": 0, "drug": "Amoxicillin 500 mg capsule", "quantity": "21 capsules", "quantity_total": 21,
               "status": "partly_given", "given_total": 14, "remaining": 7,
               "last_given_at": "2026-10-01T10:15:00+00:00", "last_pharmacy": "Kenema Pharmacy No. 4"}],
    "dispenses": [{"dispense_id": "dsp_01J9", "at": "2026-10-01T10:15:00+00:00",
                   "pharmacy_name": "Kenema Pharmacy No. 4", "status": "open",
                   "items": [{"item_index": 0, "amount": 14, "complete": False, "given_total": 14,
                              "status": "partly_given", "drug": "Amoxicillin 500 mg capsule",
                              "quantity_total": 21}]}],
}


class PrescriptionItemOut(BaseModel):
    index: int = Field(description="The item's position in the prescription (0 for the first).")
    drug: Optional[str]
    quantity: Optional[str] = Field(description="As prescribed, e.g. \"21 capsules\".")
    quantity_total: Optional[float] = Field(description="The leading number of `quantity`, if any.")
    status: Literal["not_given", "partly_given", "given"]
    given_total: Optional[float] = Field(description="How much pharmacies gave so far.")
    remaining: Optional[float] = Field(description="quantity_total minus given_total (0 once given), when known.")
    last_given_at: Optional[str] = None
    last_pharmacy: Optional[str] = None


class DispenseItemOut(BaseModel):
    item_index: int
    amount: Optional[float]
    complete: bool
    given_total: Optional[float]
    status: Literal["not_given", "partly_given", "given"]
    drug: Optional[str]
    quantity_total: Optional[float]


class DispenseOut(BaseModel):
    dispense_id: str
    at: str
    pharmacy_name: str
    status: Literal["open", "completed"]
    items: List[DispenseItemOut]


class PrescriptionOut(BaseModel):
    """A prescription with what pharmacies gave from it through Endod."""

    model_config = _examples(PRESCRIPTION_EXAMPLE)
    id: str = Field(description="The record id (from the Location of the MedicationRequest you sent).")
    patient: FollowUpPatient
    title: str
    version: int
    retracted: bool
    status: Literal["not_dispensed", "partly", "fully"]
    items: List[PrescriptionItemOut]
    dispenses: List[DispenseOut] = Field(description="Every dispense, oldest first.")
    sample: Optional[bool] = None


# --- queue ------------------------------------------------------------------------------------------------

class CheckInBody(BaseModel):
    """Check a patient in to a doctor's queue for today: by a confirmed in-person
    booking (which links the patient to Endod), a registered patient, or a walk-in."""

    model_config = _examples({"doctor_id": "c0ffee00c0ffee00c0ffee00c0ffee00", "patient_mrn": "SPH-000124"},
                             {"booking_id": "9f0c2b7a1e4d4f6a8b3c5d7e9f1a2b4c"},
                             {"doctor_id": "c0ffee00c0ffee00c0ffee00c0ffee00",
                              "walk_in": {"name": "Kebede Alemu", "phone": "+251922345678"}})
    doctor_id: OptionalText = Field(default=None, max_length=32,
                                    description="The doctor (GET /doctors); default: the booking's doctor.")
    booking_id: OptionalText = Field(default=None, max_length=32)
    patient_mrn: OptionalText = Field(default=None, max_length=40)
    walk_in: Optional[WalkIn] = Field(default=None, description="Name and phone (for the SMS when their turn comes).")

    @model_validator(mode="after")
    def _one_way(self):
        if self.walk_in is not None and (self.booking_id or self.patient_mrn):
            raise ValueError("a walk-in has no booking or patient record")
        if self.walk_in is None and not (self.booking_id or self.patient_mrn):
            raise ValueError("give a booking, a patient or a walk-in")
        return self


class QueueEntryOut(BaseModel):
    id: str
    ticket: int
    status: Literal["waiting", "called", "done", "skipped", "cancelled"]
    ahead: int = Field(description="Open entries ahead of this one.")
    patient_name: str
    phone: Optional[str]
    endod_id: Optional[str]
    mrn: Optional[str]
    booking_id: Optional[str]
    checked_in_at: str
    called_at: Optional[str]
    finished_at: Optional[str]
    day: Optional[str] = Field(default=None, description="Leftovers only: the day they were checked in.")


QUEUE_EXAMPLE = {
    "doctor": {"id": "c0ffee00c0ffee00c0ffee00c0ffee00", "full_name": "Dr. Abebe Kebede"},
    "entries": [{"id": "0e1d2c3b4a5968778695a4b3c2d1e0f1", "ticket": 1, "status": "called", "ahead": 0,
                 "patient_name": "Almaz Tefera", "phone": "+251911234567", "endod_id": "DE482731",
                 "mrn": "SPH-000124", "booking_id": None, "checked_in_at": "2026-10-01T06:05:00+00:00",
                 "called_at": "2026-10-01T06:20:00+00:00", "finished_at": None}],
    "leftovers": [], "waiting": 0,
    "called": {"id": "0e1d2c3b4a5968778695a4b3c2d1e0f1", "ticket": 1, "status": "called", "ahead": 0,
               "patient_name": "Almaz Tefera", "phone": "+251911234567", "endod_id": "DE482731",
               "mrn": "SPH-000124", "booking_id": None, "checked_in_at": "2026-10-01T06:05:00+00:00",
               "called_at": "2026-10-01T06:20:00+00:00", "finished_at": None},
}


class QueueOut(BaseModel):
    """A doctor's queue for the day."""

    model_config = _examples(QUEUE_EXAMPLE)
    doctor: DoctorRef
    entries: List[QueueEntryOut]
    leftovers: List[QueueEntryOut] = Field(description="Yesterday's entries still open (called first).")
    waiting: int
    called: Optional[QueueEntryOut]
    sample: Optional[bool] = None


class CheckInOut(QueueOut):
    model_config = _examples({**QUEUE_EXAMPLE, "entry_id": "0e1d2c3b4a5968778695a4b3c2d1e0f1", "ticket": 1})
    entry_id: str
    ticket: int


class QueueBoard(BaseModel):
    model_config = _examples({"day": "2026-10-01", "today": "2026-10-01", "notify_ahead": 3,
                              "queues": [QUEUE_EXAMPLE]})
    day: str
    today: str
    notify_ahead: int = Field(description="A patient is told when this many or fewer are ahead.")
    queues: List[QueueOut]


# --- webhooks --------------------------------------------------------------------------------------------

class _Envelope(BaseModel):
    id: str = Field(description="evt_...; the same event may arrive more than once: skip repeats by id.")
    type: str
    created: str = Field(description="When the event happened (ISO 8601).")
    hospital_id: str
    mode: Literal["live", "test"]


class BookingEventData(BaseModel):
    booking_id: str
    endod_appointment_id: str
    status: Literal["awaiting_doctor", "confirmed", "rejected", "cancelled", "completed"]
    visit_mode: Literal["in_person", "video"]
    service: Optional[str]
    scheduled_at: str
    duration_minutes: int
    patient: Dict[str, Optional[str]] = Field(description="`endod_id` only.")


class BookingEvent(_Envelope):
    """booking.created, booking.confirmed, booking.cancelled: fetch the booking (GET /bookings/{id}) for the rest."""

    type: Literal["booking.created", "booking.confirmed", "booking.cancelled"]
    data: BookingEventData


class PatientEventData(BaseModel):
    patient_id: str
    mrn: str = Field(description="The hospital number.")
    endod_id: Optional[str]
    request_id: Optional[str] = Field(default=None, description="patient.linked and patient.link_refused: the "
                                                                "link request answered (null when a booking's "
                                                                "check-in linked the patient).")
    reason: Optional[str] = Field(default=None, description="patient.link_refused only: `not_found`, "
                                                            "`not_verified`, `already_linked`, ...")


class PatientEvent(_Envelope):
    """patient.linked, patient.link_refused, patient.unlinked."""

    type: Literal["patient.linked", "patient.link_refused", "patient.unlinked"]
    data: PatientEventData


class DispensedPatient(BaseModel):
    patient_id: str
    mrn: str
    endod_id: str


class PrescriptionDispensedData(BaseModel):
    prescription_id: str = Field(description="GET /prescriptions/{prescription_id} for the items.")
    dispense_id: str
    dispense_status: Literal["open", "completed"] = Field(description="This dispense: `completed` when the "
                                                                      "pharmacy closed the prescription.")
    dispensing_status: Literal["partly", "fully"] = Field(description="The prescription as a whole.")
    dispensed_at: str
    patient: DispensedPatient


class PrescriptionDispensedEvent(_Envelope):
    """prescription.dispensed: ids and statuses only (never a drug or an amount)."""

    type: Literal["prescription.dispensed"]
    data: PrescriptionDispensedData


class EndpointTestEvent(_Envelope):
    """endpoint.test: "Send test event" in the portal (the only event a Test connection gets)."""

    type: Literal["endpoint.test"]
    data: Dict[str, str]


def _event(event_type: str, data: Dict[str, Any], mode: str = "live") -> Dict[str, Any]:
    return {"id": "evt_8c1f0e2d3b4a59687766a5b4", "type": event_type, "created": "2026-10-01T06:00:00+00:00",
            "hospital_id": "2f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c", "mode": mode, "data": data}


_BOOKING_DATA = {"booking_id": "9f0c2b7a1e4d4f6a8b3c5d7e9f1a2b4c", "endod_appointment_id": "apt_7d1c9e",
                 "status": "confirmed", "visit_mode": "in_person", "service": "general_medicine",
                 "scheduled_at": "2026-10-02T06:30:00+00:00", "duration_minutes": 30,
                 "patient": {"endod_id": "DE482731"}}
_PATIENT_DATA = {"patient_id": "5f0c1e2d3c4b5a69788796a5b4c3d2e1", "mrn": "SPH-000124", "endod_id": "DE482731"}
_REQUEST = "8b7c0f3e6a1d4c55b2e9f0a1c3d5e7f9"

#: event -> (model, when it is sent, example). Every event in app.integrations.webhooks (a test checks).
WEBHOOK_EVENTS: Dict[str, Any] = {
    "booking.created": (BookingEvent, "A patient booked a visit (in person: confirmed at once; video: "
                                      "`awaiting_doctor`).",
                        _event("booking.created", {**_BOOKING_DATA, "status": "awaiting_doctor",
                                                   "visit_mode": "video"})),
    "booking.confirmed": (BookingEvent, "An in-person booking arrived (confirmed at once), or a video visit was "
                                        "approved (in the portal or POST /bookings/{id}/approve).",
                          _event("booking.confirmed", _BOOKING_DATA)),
    "booking.cancelled": (BookingEvent, "The patient, the hospital or Endod cancelled, or a video visit was "
                                        "declined (`data.status`: cancelled or rejected).",
                          _event("booking.cancelled", {**_BOOKING_DATA, "status": "cancelled"})),
    "patient.linked": (PatientEvent, "Endod confirmed a link request (or a booking's check-in linked the "
                                     "patient): records now reach the patient's Endod app.",
                       _event("patient.linked", {**_PATIENT_DATA, "request_id": _REQUEST})),
    "patient.link_refused": (PatientEvent, "Endod refused a link request (the Endod ID and phone number do not "
                                           "match an account, the card is not valid, ...).",
                             _event("patient.link_refused", {**_PATIENT_DATA, "request_id": _REQUEST,
                                                             "reason": "not_found"})),
    "patient.unlinked": (PatientEvent, "A patient was unlinked (nothing more is sent to their Endod app).",
                         _event("patient.unlinked", _PATIENT_DATA)),
    "prescription.dispensed": (PrescriptionDispensedEvent, "A pharmacy gave medicine from one of the hospital's "
                                                           "prescriptions through Endod.",
                               _event("prescription.dispensed", {
                                   "prescription_id": "6e5d4c3b2a1908f7e6d5c4b3a2918070", "dispense_id": "dsp_01J9",
                                   "dispense_status": "open", "dispensing_status": "partly",
                                   "dispensed_at": "2026-10-01T10:15:00+00:00",
                                   "patient": {**_PATIENT_DATA}})),
    "endpoint.test": (EndpointTestEvent, "\"Send test event\" in the portal.",
                      _event("endpoint.test", {"message": "A test event from Endod: your endpoint works."},
                             mode="test")),
}
