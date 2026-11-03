"""The patient journey through the integration API: everything the hospital
portal does, for hospitals that keep their own system and use Endod as a
layer (docs/integrations.md, sections 4 to 8; webhooks in section 9).

Every endpoint calls the portal's own domain code (app/api/patients.py,
history.py, bookings.py, queue.py; app/bookings.py, app/linking.py,
app/dispensing.py), so the rules, the audit log, the events to the Endod
platform and the webhooks are the same whichever way a change arrives. The
API acts for the hospital (as an administrator would; no staff member), and
names patients by their hospital number (MRN).

* Every call: an access token with the endpoint's scope (403
  ``insufficient_scope`` otherwise), the connection's address allow-list,
  the hospital approved and not suspended, 60 requests a minute, the request
  log. Data is read and written in a transaction of the caller's hospital
  (row-level security): another hospital's patient, booking or prescription
  is "not found".
* POSTs take an ``Idempotency-Key`` (:func:`app.integrations.calls.run`).
* Changes are audited with the connection's client ID (``via:
  integration``).
* Test connections: everything is checked as in live mode, the answers are
  made up (``"sample": true``), nothing is written, and no patient is looked
  up (the answer never says whether a hospital number or Endod ID exists).
  Booking decisions are tried on made-up bookings with the real rules,
  inside a savepoint that is always rolled back.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time as clock, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Path, Query, Request
from pydantic import AwareDatetime
from sqlalchemy import select

from app import bookings as booking_rules, dispensing, records
from app.api import bookings as bookings_api, history, patients as patients_api, queue as queue_api
from app.auth import audit
from app.config import get_settings
from app.db import ensure_aware, session_scope
from app.integrations import apidoc as D, scopes as S, schemas as M
from app.integrations.calls import is_test, needs, run, via
from app.integrations.tokens import Caller
from app.models import (
    Booking, BookingStatus, ClinicalRecord, Department, Hospital, Patient, QueueStatus, RecordCategory, Role,
    StaffUser, Visit,
)

IDEMPOTENCY = Header(default=None, alias="Idempotency-Key", max_length=255,
                     description="Your unique id for this request: sent again (a retry), the first answer is "
                                 "answered again for 24 hours (`Idempotent-Replayed: true`); the same key with "
                                 "another request is refused (422).")
MRN = Path(max_length=40, description="The hospital number Endod issued, e.g. SPH-000124.")


def _iso(value: Optional[datetime]) -> Optional[str]:
    return ensure_aware(value).isoformat() if value else None


def _example(*pairs) -> Dict[str, Dict[str, Any]]:
    return {name: {"summary": summary, "value": value} for name, summary, value in pairs}


# --- patients -------------------------------------------------------------------------------------------------

def patient_by_mrn(session, hospital_id: str, mrn: str, lock: bool = False) -> Patient:
    query = select(Patient).where(Patient.hospital_id == hospital_id, Patient.mrn == mrn.strip().upper())
    patient = session.scalar(query.with_for_update() if lock else query)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return patient


def link_out(session, patient: Patient) -> Dict[str, Any]:
    payload = history.link_payload(session, patient)
    latest = payload["request"]
    if patient.dedan_id:
        status = "linked"
    elif latest and latest["status"] in ("pending", "refused"):
        status = latest["status"]
    else:
        status = "not_linked"
    request = None
    if latest:
        request = {"id": latest["id"], "endod_id": latest["dedan_id"], "method": latest["method"],
                   "status": latest["status"], "reason": latest["reason"], "created_at": latest["created_at"],
                   "decided_at": latest["decided_at"]}
    return {"status": status, "endod_id": patient.dedan_id, "claimed_endod_id": patient.claimed_dedan_id,
            "request": request}


def patient_out(session, patient: Patient) -> Dict[str, Any]:
    hospital = session.get(Hospital, patient.hospital_id)
    row = patients_api._payloads(session, [patient], patients_api._today(hospital), Role.ADMIN)[0]
    keys = ("id", "mrn", "full_name", "full_name_am", "sex", "date_of_birth", "dob_estimated", "age_years", "phone",
            "address", "emergency_contact", "payer", "payer_number", "status", "created_at")
    return {**{k: row[k] for k in keys}, "link": link_out(session, patient)}


def _sample_patient(mrn: str, body: Optional[M.PatientRegistration] = None) -> Dict[str, Any]:
    today = date.today()
    born = body.date_of_birth if body else date(today.year - 30, 1, 1)
    if body and born is None and body.age_years is not None:
        born = date(today.year - body.age_years, 1, 1)
    return {
        "id": "test-mode", "mrn": mrn, "full_name": body.full_name if body else "Sample Patient",
        "full_name_am": body.full_name_am if body else None, "sex": body.sex if body else "female",
        "date_of_birth": born.isoformat() if born else None,
        "dob_estimated": bool(body and body.date_of_birth is None and body.age_years is not None),
        "age_years": patients_api._age(born, today), "phone": body.phone if body else None,
        "address": body.address if body else None,
        "emergency_contact": {"name": body.emergency_contact_name if body else None,
                              "phone": body.emergency_contact_phone if body else None},
        "payer": body.payer if body else "cash", "payer_number": body.payer_number if body else None,
        "status": "opd", "created_at": datetime.now(timezone.utc).isoformat(),
        "link": {"status": "not_linked", "endod_id": None,
                 "claimed_endod_id": body.claimed_dedan_id if body else None, "request": None},
        "sample": True,
    }


# --- bookings -------------------------------------------------------------------------------------------------

def _doctor_names(session, ids) -> Dict[str, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {u.id: u.full_name for u in session.scalars(select(StaffUser).where(StaffUser.id.in_(ids)))}


def booking_out(b: Booking, doctors: Dict[str, str]) -> Dict[str, Any]:
    return {
        "id": b.id, "endod_appointment_id": b.external_id, "status": b.status, "visit_mode": b.visit_mode,
        "service": b.service, "scheduled_at": _iso(b.scheduled_at), "duration_minutes": b.duration_minutes,
        # "online" (paid to Endod) or "at_hospital" (collect `price`, in birr, at the visit).
        "payment": b.payment, "price": f"{Decimal(b.price) / 100:.2f}",
        "patient": {"endod_id": b.patient_dedan_id, "name": b.patient_name, "phone": b.patient_phone},
        "doctor": {"id": b.doctor_id, "full_name": doctors.get(b.doctor_id, "")} if b.doctor_id else None,
        "reason": b.reason, "decided_at": _iso(b.decided_at),
        "created_at": _iso(b.created_at), "updated_at": _iso(b.updated_at or b.created_at),
    }


def video_visits() -> bool:
    """Video visits are on (HOSPITAL_VIDEO_VISITS_ENABLED; off by default)."""
    return get_settings().VIDEO_VISITS_ENABLED


def _video_only() -> None:
    """404 for the video-only endpoints while video visits are off (as if they did not exist)."""
    if not video_visits():
        raise HTTPException(status_code=404, detail="Not Found")


def _sample_rows() -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    base = datetime.combine(now.date() + timedelta(days=1), clock(6, 0), timezone.utc)
    started = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    return [
        {"n": 1, "mode": "in_person", "status": "confirmed", "at": base, "payment": "at_hospital"},
        # A video visit to approve or decline, while video visits are on (HOSPITAL_VIDEO_VISITS_ENABLED).
        {"n": 2, "mode": "video", "status": "awaiting_doctor", "at": base + timedelta(hours=1), "payment": "online"}
        if video_visits() else
        {"n": 2, "mode": "in_person", "status": "confirmed", "at": base + timedelta(hours=1), "payment": "online"},
        {"n": 3, "mode": "in_person", "status": "cancelled", "at": base + timedelta(hours=2), "payment": "online"},
        # Already started: one a Test connection can mark completed.
        {"n": 4, "mode": "in_person", "status": "confirmed", "at": started, "payment": "at_hospital"},
    ]


def sample_booking(row: Dict[str, Any], hospital_id: Optional[str] = None) -> Booking:
    """A made-up booking (never saved): what a Test connection sees and decides on."""
    n = row["n"]
    created = row["at"] - timedelta(days=2)
    return Booking(id=f"sample{n:0>26}", hospital_id=hospital_id, external_id=f"sample-appointment-{n}",
                   patient_dedan_id=f"DE00000{n}", patient_name=f"Sample Patient {n}", patient_phone=None,
                   visit_mode=row["mode"], service="general_medicine", scheduled_at=row["at"], duration_minutes=30,
                   price=15000, payment=row["payment"], status=row["status"],
                   reason="Cancelled by the patient." if row["status"] == "cancelled" else None,
                   created_at=created, updated_at=created)


def sample_bookings() -> List[Dict[str, Any]]:
    return [{**booking_out(sample_booking(r), {}), "sample": True} for r in _sample_rows()]


def _sample_for(booking_id: str, hospital_id: str) -> Booking:
    for row in _sample_rows():
        booking = sample_booking(row, hospital_id)
        if booking.id == booking_id:
            return booking
    raise HTTPException(status_code=404, detail="Booking not found.")


def _decide(who: Caller, booking_id: str, action):
    """work(session) for a booking decision: the portal's rules (app/bookings.py),
    events and audit; on a Test connection, the same rules tried on a made-up
    booking inside a savepoint that is always rolled back."""
    def work(session):
        try:
            if is_test(who):
                booking = _sample_for(booking_id, who.hospital_id)
                savepoint = session.begin_nested()
                try:
                    action(session, booking)
                    names = _doctor_names(session, [booking.doctor_id])
                finally:
                    savepoint.rollback()
                return 200, {**booking_out(booking, names), "sample": True}
            booking = bookings_api.decide(session, who.hospital_id, booking_id, action, None, via(who))
            return 200, booking_out(booking, _doctor_names(session, [booking.doctor_id]))
        except booking_rules.BookingError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return work


# --- follow-ups -----------------------------------------------------------------------------------------------

def follow_up_out(session, visit: Visit, patient: Patient) -> Dict[str, Any]:
    doctor = None
    if visit.doctor_id:
        doctor = {"id": visit.doctor_id, "full_name": records.doctor_name(session, visit) or ""}
    return {"id": visit.id, "patient": {"mrn": patient.mrn, "endod_id": patient.dedan_id},
            "date": visit.follow_up_on.isoformat() if visit.follow_up_on else None, "note": visit.follow_up_note,
            "status": "scheduled" if visit.follow_up_on else "cancelled", "doctor": doctor,
            "booking_id": visit.booking_id, "sent_to_endod": bool(visit.follow_up_sent_to),
            "created_at": _iso(visit.created_at)}


def _sample_follow_up(mrn: str, on: Optional[date], note: Optional[str], status: str = "scheduled",
                      doctor: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return {"id": "sample-follow-up-1", "patient": {"mrn": mrn, "endod_id": None},
            "date": on.isoformat() if on else None, "note": note, "status": status, "doctor": doctor,
            "booking_id": None, "sent_to_endod": False, "created_at": datetime.now(timezone.utc).isoformat(),
            "sample": True}


def _doctor(session, hospital_id: str, doctor_id: Optional[str]) -> Optional[Dict[str, str]]:
    if not doctor_id:
        return None
    doctor = session.scalar(select(StaffUser).where(StaffUser.id == doctor_id, StaffUser.hospital_id == hospital_id,
                                                    StaffUser.role == Role.DOCTOR))
    if doctor is None:
        raise HTTPException(status_code=400, detail="Unknown doctor.")
    return {"id": doctor.id, "full_name": doctor.full_name}


# --- prescriptions --------------------------------------------------------------------------------------------

def _number(value: Any) -> Optional[float]:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def prescription_out(record: ClinicalRecord, patient: Patient, dispenses) -> Dict[str, Any]:
    shown = dispensing.dispensing_payload(record, dispenses)
    try:
        written = json.loads(record.details).get("items") or []
    except (ValueError, AttributeError):
        written = []
    items = []
    for index, item in enumerate(written):
        item = item if isinstance(item, dict) else {}
        total = dispensing.quantity_total(item.get("quantity"))
        given, done, last_at, pharmacy = 0, False, None, None
        for d in shown["dispenses"]:
            for line in d["items"]:
                if line["item_index"] != index:
                    continue
                # given_total is what pharmacies gave so far; it never goes down.
                if _number(line.get("given_total")) is not None:
                    given = max(given, line["given_total"])
                elif _number(line.get("amount")) is not None:
                    given = given + line["amount"]
                done = done or line["status"] == "given" or bool(line.get("complete"))
                if line.get("amount"):
                    last_at, pharmacy = d["at"], d["pharmacy_name"]
        # From everything given, never from the last line alone (a later "nothing given" keeps what was).
        status = "given" if done else ("partly_given" if given > 0 else "not_given")
        remaining = None
        if status == "given":
            remaining = 0
        elif total is not None:
            remaining = max(total - given, 0)
        items.append({"index": index, "drug": item.get("drug"), "quantity": item.get("quantity"),
                      "quantity_total": total, "status": status, "given_total": given, "remaining": remaining,
                      "last_given_at": last_at, "last_pharmacy": pharmacy})
    return {"id": record.id, "patient": {"mrn": patient.mrn, "endod_id": patient.dedan_id}, "title": record.title,
            "version": record.version, "retracted": record.retracted, "status": shown["status"], "items": items,
            "dispenses": shown["dispenses"]}


SAMPLE_PRESCRIPTION_ID = "sample-prescription-1"


def _sample_prescription() -> Dict[str, Any]:
    return {**json.loads(json.dumps(M.PRESCRIPTION_EXAMPLE)), "id": SAMPLE_PRESCRIPTION_ID,
            "patient": {"mrn": "TEST-000001", "endod_id": "DE000001"}, "sample": True}


# --- queue ----------------------------------------------------------------------------------------------------

def queue_out(session, payload: Dict[str, Any]) -> Dict[str, Any]:
    """The portal's queue as the API shows it: patients by hospital number and Endod ID."""
    entries = payload["entries"] + payload["leftovers"]
    ids = {e["patient_id"] for e in entries if e.get("patient_id")}
    mrns = {p.id: p.mrn for p in session.scalars(select(Patient).where(Patient.id.in_(ids)))} if ids else {}

    def entry(e: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if e is None:
            return None
        out = {k: v for k, v in e.items() if k not in ("patient_id", "dedan_id")}
        return {**out, "endod_id": e.get("dedan_id"), "mrn": mrns.get(e.get("patient_id"))}

    return {**{k: v for k, v in payload.items() if k not in ("entries", "leftovers", "called")},
            "entries": [entry(e) for e in payload["entries"]], "leftovers": [entry(e) for e in payload["leftovers"]],
            "called": entry(payload["called"])}


SAMPLE_ENTRY = "sample-entry-"


def _sample_queue(doctor: Dict[str, str], status: str = "waiting", name: str = "Sample Patient",
                  phone: Optional[str] = None) -> Dict[str, Any]:
    """A made-up queue of one patient; the entry's id names the doctor
    (``sample-entry-<doctor id>``), so finishing it answers the same queue."""
    now = datetime.now(timezone.utc).isoformat()
    item = {"id": f"{SAMPLE_ENTRY}{doctor['id']}", "ticket": 1, "status": status, "ahead": 0, "patient_name": name, "phone": phone,
            "endod_id": None, "mrn": None, "booking_id": None, "checked_in_at": now,
            "called_at": now if status != "waiting" else None,
            "finished_at": now if status in ("done", "skipped", "cancelled") else None}
    open_ = status in QueueStatus.OPEN
    return {"doctor": doctor, "entries": [item], "leftovers": [],
            "waiting": 1 if status == "waiting" else 0, "called": item if status == "called" and open_ else None,
            "sample": True}


# --- the routes -----------------------------------------------------------------------------------------------

def add_routes(api: FastAPI) -> None:  # noqa: C901 -- one place lists every journey endpoint
    # Patients ------------------------------------------------------------------------------------------------

    @api.post("/patients", status_code=201, **D.operation(
        [S.PATIENTS_WRITE], "Register a patient",
        "Register a patient at the hospital, as the portal's registration form does (same checks). Endod issues "
        "the hospital number (`mrn`): keep it in your system and name the patient by it everywhere. A patient "
        "with the same name and phone number is refused (409) unless `confirm_duplicate` is set. An Endod ID the "
        "patient gives is kept as a claim (`claimed_endod_id`); link the patient to confirm it.\n\n"
        "Test connections: checked, nothing is stored, a made-up hospital number (TEST-000001).",
        D.ok(201, M.PatientOut, "Registered.", M.PATIENT_EXAMPLE, D.IDEMPOTENT_REPLAY), [400, 409],
        {409: "Almaz Tefera with this phone number is already registered as SPH-000124. Open that record, or "
              "register again with confirm_duplicate set."}, [D.PATIENTS]))
    async def register_patient(
            request: Request,
            body: M.PatientRegistration = Body(openapi_examples=_example(
                ("full", "With a date of birth", M.REGISTRATION_EXAMPLE),
                ("age", "With an age only", {"full_name": "Kebede Alemu", "sex": "male", "age_years": 45,
                                             "phone": "+251922345678"}))),
            who: Caller = Depends(needs(S.PATIENTS_WRITE)), idempotency_key: Optional[str] = IDEMPOTENCY):
        def work(session):
            hospital = session.get(Hospital, who.hospital_id)
            if is_test(who):
                patients_api.check_registration(hospital, body)
                return 201, _sample_patient("TEST-000001", body)
            patient = patients_api.register(session, who.hospital_id, body, None)
            audit(session, who.hospital_id, None, "patient_registered", "patient", patient.id,
                  {"mrn": patient.mrn, **via(who)})
            return 201, patient_out(session, patient)
        return await run(request, who, idempotency_key, work,
                         "The registration conflicts with another one made at the same time; send it again.")

    @api.get("/patients/{mrn}", **D.operation(
        [S.PATIENTS_READ], "Read a patient by hospital number",
        "The patient's details and where their link to Endod stands (`link.status`: not_linked, pending, linked, "
        "refused). Opening a patient is audited, as in the portal.\n\nTest connections: a made-up patient, the "
        "same whatever the number (never says whether it exists).",
        D.ok(200, M.PatientOut, "The patient.", M.PATIENT_EXAMPLE), [404], tags=[D.PATIENTS]))
    def read_patient(mrn: str = MRN, who: Caller = Depends(needs(S.PATIENTS_READ))) -> Dict[str, Any]:
        if is_test(who):
            return _sample_patient(mrn.strip().upper())
        with session_scope(who.hospital_id) as session:
            patient = patient_by_mrn(session, who.hospital_id, mrn)
            audit(session, who.hospital_id, None, "patient_viewed", "patient", patient.id, via(who))
            return patient_out(session, patient)

    @api.post("/patients/{mrn}/link", status_code=202, **D.operation(
        [S.PATIENTS_WRITE], "Link a patient to their Endod account",
        "Ask Endod to confirm the patient's account, exactly as the portal does: by the health card's QR "
        "(`card_url`), or by the Endod ID and the phone number on the account. Answers 202 with `status: pending`; "
        "Endod's answer arrives as a webhook (`patient.linked` or `patient.link_refused`) and in GET "
        "/patients/{mrn}. Once linked, the patient's records and follow-ups reach their Endod app.\n\n"
        "Test connections: checked, a made-up pending answer; nothing is sent to Endod.",
        D.ok(202, M.LinkOut, "Asked; Endod is checking.", None, D.IDEMPOTENT_REPLAY), [400, 404, 409],
        {409: "This patient is already linked to DE482731. Unlink first."}, [D.PATIENTS]))
    async def link_patient(
            request: Request, mrn: str = MRN,
            body: M.LinkRequestBody = Body(openapi_examples=_example(
                ("phone", "Endod ID and phone number", {"endod_id": "DE482731", "phone": "+251911234567"}),
                ("card", "The health card's QR", {"card_url": "https://endod-health.com/card/DE482731?s=Q2FyZFNpZ25"
                                                              "hdHVyZS4uLg"}))),
            who: Caller = Depends(needs(S.PATIENTS_WRITE)), idempotency_key: Optional[str] = IDEMPOTENCY):
        dedan_id, signature = history.link_target(body)  # refused before any database work

        def work(session):
            if is_test(who):
                now = datetime.now(timezone.utc).isoformat()
                return 202, {"status": "pending", "endod_id": None, "claimed_endod_id": None, "request": {
                    "id": "test-mode", "endod_id": dedan_id, "method": "card" if signature else "phone",
                    "status": "pending", "reason": None, "created_at": now, "decided_at": None}, "sample": True}
            patient = patient_by_mrn(session, who.hospital_id, mrn, lock=True)
            history.ask_link(session, patient, body, None, via(who))
            return 202, link_out(session, patient)
        return await run(request, who, idempotency_key, work)

    @api.delete("/patients/{mrn}/link", **D.operation(
        [S.PATIENTS_WRITE], "Unlink a patient (or withdraw a pending request)",
        "Nothing more is sent to the patient's Endod app; the webhook `patient.unlinked` follows (for a linked "
        "patient).\n\nTest connections: a made-up answer; nothing changes.",
        D.ok(200, M.LinkOut, "Unlinked.", {"status": "not_linked", "endod_id": None, "claimed_endod_id": None,
                                           "request": None}), [404], tags=[D.PATIENTS]))
    def unlink_patient(mrn: str = MRN, who: Caller = Depends(needs(S.PATIENTS_WRITE))) -> Dict[str, Any]:
        if is_test(who):
            return {"status": "not_linked", "endod_id": None, "claimed_endod_id": None, "request": None,
                    "sample": True}
        with session_scope(who.hospital_id) as session:
            patient = patient_by_mrn(session, who.hospital_id, mrn, lock=True)
            history.end_link(session, patient, None, via(who))
            return link_out(session, patient)

    # Bookings ------------------------------------------------------------------------------------------------

    @api.get("/bookings", **D.operation(
        [S.BOOKINGS_READ], "List bookings",
        "Bookings patients made through Endod, by scheduled time (earliest first). Never the note the patient "
        "typed.\n\nTest connections: made-up bookings (`sample: true`).",
        D.ok(200, M.BookingList, "The bookings.", {"items": [M.BOOKING_EXAMPLE]}), [400], tags=[D.BOOKINGS]))
    def list_bookings(status: Optional[str] = Query(default=None, description=f"One of {list(BookingStatus.ALL)}."),
                      scheduled_from: Optional[AwareDatetime] = Query(default=None, alias="from",
                                                                      description="Scheduled at or after."),
                      scheduled_to: Optional[AwareDatetime] = Query(default=None, alias="to",
                                                                    description="Scheduled before."),
                      updated_since: Optional[AwareDatetime] = Query(default=None,
                                                                     description="Changed at or after."),
                      limit: int = Query(default=100, ge=1, le=500),
                      who: Caller = Depends(needs(S.BOOKINGS_READ))) -> Dict[str, Any]:
        if status is not None and status not in BookingStatus.ALL:
            raise HTTPException(status_code=400, detail=f"status must be one of {list(BookingStatus.ALL)}.")
        if is_test(who):
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
            rows = list(session.scalars(query.order_by(Booking.scheduled_at, Booking.id).limit(limit)))
            names = _doctor_names(session, [b.doctor_id for b in rows])
            return {"items": [booking_out(b, names) for b in rows]}

    @api.get("/bookings/{booking_id}", **D.operation(
        [S.BOOKINGS_READ], "Read a booking", "One booking (another hospital's is never found).",
        D.ok(200, M.BookingOut, "The booking.", M.BOOKING_EXAMPLE), [404], tags=[D.BOOKINGS]))
    def read_booking(booking_id: str = Path(max_length=32), who: Caller = Depends(needs(S.BOOKINGS_READ))) \
            -> Dict[str, Any]:
        if is_test(who):
            found = next((b for b in sample_bookings() if b["id"] == booking_id), None)
            if found is None:
                raise HTTPException(status_code=404, detail="Booking not found.")
            return found
        with session_scope(who.hospital_id) as session:
            booking = session.scalar(select(Booking).where(Booking.id == booking_id,
                                                           Booking.hospital_id == who.hospital_id))
            if booking is None:
                raise HTTPException(status_code=404, detail="Booking not found.")
            return booking_out(booking, _doctor_names(session, [booking.doctor_id]))

    test_note = ("\n\nTest connections: tried with the same rules on the made-up bookings of GET /bookings; "
                 "nothing changes and nothing is sent.")
    decided = D.ok(200, M.BookingOut, "The booking, decided.", M.BOOKING_EXAMPLE, D.IDEMPOTENT_REPLAY)

    # Video visits only (HOSPITAL_VIDEO_VISITS_ENABLED): while they are off, approve and decline are left
    # out of the OpenAPI document and answer 404, before anything else is checked.
    video = video_visits()

    @api.post("/bookings/{booking_id}/approve", include_in_schema=video, dependencies=[Depends(_video_only)],
              **D.operation(
        [S.BOOKINGS_WRITE], "Approve a video visit",
        "A video visit awaiting a doctor (`awaiting_doctor`) is confirmed: the doctor becomes its doctor and a "
        "video room is opened. Endod tells the patient (`appointment.confirmed`); webhook `booking.confirmed`. "
        "A visit whose time has passed can no longer be approved (409)." + test_note,
        decided, [400, 404, 409], {409: "This visit is not waiting for approval."}, [D.BOOKINGS]))
    async def approve_booking(request: Request, booking_id: str = Path(max_length=32),
                              body: M.ApproveBody = Body(openapi_examples=_example(
                                  ("doctor", "The approving doctor", {"doctor_id": "c0ffee00c0ffee00c0ffee00c0ffee00"}))),
                              who: Caller = Depends(needs(S.BOOKINGS_WRITE)),
                              idempotency_key: Optional[str] = IDEMPOTENCY):
        action = bookings_api.approve_action(who.hospital_id, body.doctor_id, None)
        return await run(request, who, idempotency_key, _decide(who, booking_id, action))

    reason_examples = _example(("reason", "Told to the patient",
                                {"reason": "The doctor is away that day; please book another day."}))

    @api.post("/bookings/{booking_id}/decline", include_in_schema=video, dependencies=[Depends(_video_only)],
              **D.operation(
        [S.BOOKINGS_WRITE], "Decline a video visit",
        "A video visit awaiting a doctor is declined with a reason (told to the patient). A patient who paid "
        "online is refunded by Endod (`appointment.rejected`); webhook `booking.cancelled` with status "
        "`rejected`. Cancel a confirmed visit instead." + test_note,
        decided, [404, 409], {409: "Only a visit waiting for approval can be rejected; cancel a confirmed one."},
        [D.BOOKINGS]))
    async def decline_booking(request: Request, booking_id: str = Path(max_length=32),
                              body: M.ReasonBody = Body(openapi_examples=reason_examples),
                              who: Caller = Depends(needs(S.BOOKINGS_WRITE)),
                              idempotency_key: Optional[str] = IDEMPOTENCY):
        action = lambda s, b: booking_rules.reject(s, b, body.reason, None)  # noqa: E731
        return await run(request, who, idempotency_key, _decide(who, booking_id, action))

    @api.post("/bookings/{booking_id}/cancel", **D.operation(
        [S.BOOKINGS_WRITE], "Cancel a booking (hospital side)",
        "Cancel a confirmed booking, with a reason told to the patient (one still awaiting a doctor is declined). "
        "A patient who paid online is refunded by Endod (`appointment.cancelled`); webhook `booking.cancelled`."
        + test_note, decided, [404, 409], tags=[D.BOOKINGS]))
    async def cancel_booking(request: Request, booking_id: str = Path(max_length=32),
                             body: M.ReasonBody = Body(openapi_examples=reason_examples),
                             who: Caller = Depends(needs(S.BOOKINGS_WRITE)),
                             idempotency_key: Optional[str] = IDEMPOTENCY):
        action = lambda s, b: booking_rules.cancel(s, b, body.reason, None)  # noqa: E731
        return await run(request, who, idempotency_key, _decide(who, booking_id, action))

    @api.post("/bookings/{booking_id}/complete", **D.operation(
        [S.BOOKINGS_WRITE], "Mark a visit completed",
        "A confirmed visit that has started is completed (`appointment.completed` to Endod). No body." + test_note,
        decided, [404, 409], {409: "A visit cannot be completed before it starts."}, [D.BOOKINGS]))
    async def complete_booking(request: Request, booking_id: str = Path(max_length=32),
                               who: Caller = Depends(needs(S.BOOKINGS_WRITE)),
                               idempotency_key: Optional[str] = IDEMPOTENCY):
        action = lambda s, b: booking_rules.complete(s, b, None)  # noqa: E731
        return await run(request, who, idempotency_key, _decide(who, booking_id, action))

    # Doctors -------------------------------------------------------------------------------------------------

    @api.get("/doctors", **D.operation(
        [S.BOOKINGS_WRITE, S.QUEUE, S.FOLLOWUPS], "List the hospital's doctors",
        ("Active doctors, to name one when approving a video visit, checking a patient in or setting a follow-up."
         if video else "Active doctors, to name one when checking a patient in or setting a follow-up."),
        D.ok(200, M.DoctorList, "The doctors."), tags=[D.DOCTORS]))
    def list_doctors(who: Caller = Depends(needs(S.BOOKINGS_WRITE, S.QUEUE, S.FOLLOWUPS))) -> Dict[str, Any]:
        with session_scope(who.hospital_id) as session:
            rows = list(session.scalars(select(StaffUser).where(
                StaffUser.hospital_id == who.hospital_id, StaffUser.role == Role.DOCTOR,
                StaffUser.active.is_(True)).order_by(StaffUser.full_name)))
            ids = {d.department_id for d in rows if d.department_id}
            departments = {d.id: d.name for d in session.scalars(select(Department).where(Department.id.in_(ids)))} \
                if ids else {}
            return {"items": [{"id": d.id, "full_name": d.full_name, "full_name_am": d.full_name_am,
                               "department": departments.get(d.department_id)} for d in rows]}

    # Follow-ups ----------------------------------------------------------------------------------------------

    @api.post("/patients/{mrn}/follow-ups", status_code=201, **D.operation(
        [S.FOLLOWUPS], "Set a follow-up",
        "A follow-up date for the patient, as a doctor sets one in the portal (after today, within two years). A "
        "linked patient gets an SMS now and a reminder before the day (`visit.follow_up` to Endod); a patient "
        "linked later gets it then. A `booking_id` must be the patient's booking (the same confirmed or "
        "claimed Endod ID, or phone number), else 409.\n\nTest connections: checked, a made-up answer; nothing "
        "is stored or sent.",
        D.ok(201, M.FollowUpOut, "Set.", M.FOLLOW_UP_EXAMPLE, D.IDEMPOTENT_REPLAY), [400, 404, 409],
        {400: "The follow-up must be after today and within two years."}, [D.FOLLOW_UPS]))
    async def create_follow_up(request: Request, mrn: str = MRN,
                               body: M.FollowUpCreate = Body(openapi_examples=_example(
                                   ("review", "With a note and the doctor",
                                    {"date": "2026-10-15", "note": "Review the blood film result.",
                                     "doctor_id": "c0ffee00c0ffee00c0ffee00c0ffee00"}),
                                   ("date_only", "A date only", {"date": "2026-11-01"}))),
                               who: Caller = Depends(needs(S.FOLLOWUPS)),
                               idempotency_key: Optional[str] = IDEMPOTENCY):
        def work(session):
            history.check_follow_up_date(session, who.hospital_id, body.date)
            if is_test(who):
                doctor = _doctor(session, who.hospital_id, body.doctor_id)
                return 201, _sample_follow_up(mrn.strip().upper(), body.date, body.note, doctor=doctor)
            patient = patient_by_mrn(session, who.hospital_id, mrn, lock=True)
            if body.booking_id:
                booking = session.scalar(select(Booking).where(Booking.id == body.booking_id,
                                                               Booking.hospital_id == who.hospital_id))
                if booking is None:
                    raise HTTPException(status_code=400, detail="Unknown booking.")
                if not queue_api.same_person(patient, booking, queue_api._booking_dedan(booking)):
                    raise HTTPException(status_code=409, detail="This booking is not this patient's (Endod ID or "
                                                                "phone number).")
            visit = history.open_visit(session, who.hospital_id, patient, doctor_id=body.doctor_id,
                                       booking_id=body.booking_id, started_at=None, follow_up_on=body.date,
                                       follow_up_note=body.note, actor_id=None, audit_extra=via(who))
            return 201, follow_up_out(session, visit, patient)
        return await run(request, who, idempotency_key, work)

    @api.get("/patients/{mrn}/follow-ups", **D.operation(
        [S.FOLLOWUPS], "List a patient's follow-ups",
        "The patient's scheduled follow-ups, latest date first (cancelled ones are not listed).\n\nTest "
        "connections: a made-up follow-up.",
        D.ok(200, M.FollowUpList, "The follow-ups.", {"items": [M.FOLLOW_UP_EXAMPLE]}), [404],
        tags=[D.FOLLOW_UPS]))
    def list_follow_ups(mrn: str = MRN, who: Caller = Depends(needs(S.FOLLOWUPS))) -> Dict[str, Any]:
        if is_test(who):
            return {"items": [_sample_follow_up(mrn.strip().upper(), date.today() + timedelta(days=14),
                                                "Sample follow-up.")]}
        with session_scope(who.hospital_id) as session:
            patient = patient_by_mrn(session, who.hospital_id, mrn)
            rows = session.scalars(select(Visit).where(Visit.patient_id == patient.id,
                                                       Visit.hospital_id == who.hospital_id,
                                                       Visit.follow_up_on.is_not(None))
                                   .order_by(Visit.follow_up_on.desc(), Visit.created_at.desc()))
            return {"items": [follow_up_out(session, v, patient) for v in rows]}

    @api.post("/follow-ups/{follow_up_id}/cancel", **D.operation(
        [S.FOLLOWUPS], "Cancel a follow-up",
        "Endod is told it is cancelled (the patient's reminder is withdrawn). No body.\n\nTest connections: "
        "only the made-up follow-up (sample-follow-up-1); nothing changes.",
        D.ok(200, M.FollowUpOut, "Cancelled.", {**M.FOLLOW_UP_EXAMPLE, "date": None, "note": None,
                                                "status": "cancelled", "sent_to_endod": False},
             D.IDEMPOTENT_REPLAY),
        [400, 404], {400: "This visit has no follow-up."}, [D.FOLLOW_UPS]))
    async def cancel_follow_up(request: Request, follow_up_id: str = Path(max_length=32),
                               who: Caller = Depends(needs(S.FOLLOWUPS)),
                               idempotency_key: Optional[str] = IDEMPOTENCY):
        def work(session):
            if is_test(who):
                if follow_up_id != "sample-follow-up-1":
                    raise HTTPException(status_code=404, detail="Follow-up not found.")
                return 200, _sample_follow_up("TEST-000001", None, None, status="cancelled")
            visit = session.scalar(select(Visit).where(Visit.id == follow_up_id,
                                                       Visit.hospital_id == who.hospital_id).with_for_update())
            if visit is None:
                raise HTTPException(status_code=404, detail="Follow-up not found.")
            history.change_follow_up(session, who.hospital_id, visit, None, None, None, via(who))
            return 200, follow_up_out(session, visit, session.get(Patient, visit.patient_id))
        return await run(request, who, idempotency_key, work)

    # Prescriptions -------------------------------------------------------------------------------------------

    @api.get("/prescriptions/{prescription_id}", **D.operation(
        [S.PRESCRIPTIONS_READ], "Read a prescription and what pharmacies gave",
        "A prescription of the hospital (its id is the record id in the Location of the MedicationRequest you "
        "sent, and in the webhook `prescription.dispensed`), with each item's status: `not_given`, "
        "`partly_given` or `given`, how much was given, what remains, when and where it was last given; and "
        "every dispense.\n\nTest connections: only the made-up prescription sample-prescription-1.",
        D.ok(200, M.PrescriptionOut, "The prescription.", M.PRESCRIPTION_EXAMPLE), [404],
        tags=[D.PRESCRIPTIONS]))
    def read_prescription(prescription_id: str = Path(max_length=40),
                          who: Caller = Depends(needs(S.PRESCRIPTIONS_READ))) -> Dict[str, Any]:
        if is_test(who):
            if prescription_id != SAMPLE_PRESCRIPTION_ID:
                raise HTTPException(status_code=404, detail="Prescription not found.")
            return _sample_prescription()
        with session_scope(who.hospital_id) as session:
            record = session.scalar(select(ClinicalRecord).where(
                ClinicalRecord.id == prescription_id, ClinicalRecord.hospital_id == who.hospital_id,
                ClinicalRecord.category == RecordCategory.PRESCRIPTION))
            if record is None:
                raise HTTPException(status_code=404, detail="Prescription not found.")
            patient = session.get(Patient, record.patient_id)
            found = dispensing.dispenses_of(session, [record.id]).get(record.id, [])
            audit(session, who.hospital_id, None, "patient_records_viewed", "patient", patient.id,
                  {"record_id": record.id, **via(who)})
            return prescription_out(record, patient, found)

    # Queue ---------------------------------------------------------------------------------------------------

    @api.get("/queue", **D.operation(
        [S.QUEUE], "Today's queues",
        "Every active doctor's queue for the day (default: today at the hospital), or one doctor's; today's "
        "board also shows yesterday's patients still waiting (`leftovers`, called first).\n\nTest connections: "
        "the real doctors, each with a made-up patient.",
        D.ok(200, M.QueueBoard, "The queues."), tags=[D.QUEUE]))
    def read_queue(day: Optional[date] = Query(default=None, description="The hospital's date (default today)."),
                   doctor_id: Optional[str] = Query(default=None, max_length=32),
                   who: Caller = Depends(needs(S.QUEUE))) -> Dict[str, Any]:
        with session_scope(who.hospital_id) as session:
            if is_test(who):
                # The real doctors (not patients' data), each with a made-up patient.
                today = records.hospital_today(session, who.hospital_id)
                query = select(StaffUser).where(StaffUser.hospital_id == who.hospital_id,
                                                StaffUser.role == Role.DOCTOR, StaffUser.active.is_(True))
                if doctor_id:
                    query = query.where(StaffUser.id == doctor_id)
                doctors = session.scalars(query.order_by(StaffUser.full_name))
                return {"day": (day or today).isoformat(), "today": today.isoformat(),
                        "notify_ahead": session.get(Hospital, who.hospital_id).queue_notify_ahead,
                        "queues": [_sample_queue({"id": d.id, "full_name": d.full_name}) for d in doctors]}
            payload = queue_api.board(session, who.hospital_id, day, doctor_id)
            return {**payload, "queues": [queue_out(session, q) for q in payload["queues"]]}

    @api.post("/queue/check-in", status_code=201, **D.operation(
        [S.QUEUE], "Check a patient in",
        "Check a patient in to a doctor's queue for today, with a ticket: by a confirmed in-person booking (which "
        "links the hospital patient to Endod without asking again), a registered patient (`patient_mrn`), or a "
        "walk-in (name and phone). A patient named with a booking must be the booking's patient (the same "
        "confirmed or claimed Endod ID, or phone number), else 409: check in by the booking alone, or link the "
        "patient first. Linked patients follow their place in the Endod app; anyone with a phone gets "
        "an SMS when their turn is near and when they are called.\n\nTest connections: checked, a made-up ticket "
        "(bookings: only the made-up ones; patients are never looked up).",
        D.ok(201, M.CheckInOut, "Checked in.", None, D.IDEMPOTENT_REPLAY), [400, 404, 409],
        {409: "This patient is already in this queue."}, [D.QUEUE]))
    async def check_in(request: Request,
                       body: M.CheckInBody = Body(openapi_examples=_example(
                           ("patient", "A registered patient", {"doctor_id": "c0ffee00c0ffee00c0ffee00c0ffee00",
                                                                "patient_mrn": "SPH-000124"}),
                           ("booking", "An Endod booking (its doctor, or name one)",
                            {"booking_id": "9f0c2b7a1e4d4f6a8b3c5d7e9f1a2b4c",
                             "doctor_id": "c0ffee00c0ffee00c0ffee00c0ffee00"}),
                           ("walk_in", "A walk-in", {"doctor_id": "c0ffee00c0ffee00c0ffee00c0ffee00",
                                                     "walk_in": {"name": "Kebede Alemu", "phone": "+251922345678"}}))),
                       who: Caller = Depends(needs(S.QUEUE)), idempotency_key: Optional[str] = IDEMPOTENCY):
        def work(session):
            if is_test(who):
                doctor_id = body.doctor_id
                if body.booking_id:
                    booking = _sample_for(body.booking_id, who.hospital_id)
                    if booking.status != BookingStatus.CONFIRMED or booking.visit_mode != "in_person":
                        raise HTTPException(status_code=409, detail="Only a confirmed in-person booking is "
                                                                    "checked in.")
                    doctor_id = doctor_id or booking.doctor_id  # as in live mode
                doctor = queue_api.queue_doctor(session, who.hospital_id, doctor_id)
                name = body.walk_in.name if body.walk_in else "Sample Patient"
                phone = body.walk_in.phone if body.walk_in else None
                return 201, {**_sample_queue({"id": doctor.id, "full_name": doctor.full_name}, name=name,
                                             phone=phone), "entry_id": f"{SAMPLE_ENTRY}{doctor.id}", "ticket": 1}
            patient_id = None
            if body.patient_mrn:
                patient_id = patient_by_mrn(session, who.hospital_id, body.patient_mrn).id
            portal_body = queue_api.CheckIn(doctor_id=body.doctor_id, booking_id=body.booking_id,
                                            patient_id=patient_id, walk_in=body.walk_in)
            doctor, queue, entry = queue_api.check_in_patient(session, who.hospital_id, portal_body, None, via(who),
                                                              verify_patient=True)
            return 201, {**queue_out(session, queue_api.queue_payload(session, doctor, queue)),
                         "entry_id": entry.id, "ticket": entry.ticket}
        return await run(request, who, idempotency_key, work, "This booking is already checked in.")

    @api.post("/queue/{doctor_id}/call-next", **D.operation(
        [S.QUEUE], "Call the next patient",
        "Calls the doctor's next waiting patient (yesterday's leftovers first, then by ticket); refused while "
        "someone is still called (409). The patient is told it is their turn. No body.\n\nTest connections: a "
        "made-up answer.",
        D.ok(200, M.QueueOut, "The doctor's queue.", M.QUEUE_EXAMPLE, D.IDEMPOTENT_REPLAY), [400, 409],
        {409: "Nobody is waiting."}, [D.QUEUE]))
    async def call_next(request: Request, doctor_id: str = Path(max_length=32),
                        who: Caller = Depends(needs(S.QUEUE)), idempotency_key: Optional[str] = IDEMPOTENCY):
        def work(session):
            if is_test(who):
                doctor = queue_api.queue_doctor(session, who.hospital_id, doctor_id)
                return 200, _sample_queue({"id": doctor.id, "full_name": doctor.full_name}, status="called")
            doctor, queue, earlier = queue_api.call_next_patient(session, who.hospital_id, doctor_id, None, via(who))
            return 200, queue_out(session, queue_api.queue_payload(session, doctor, queue, earlier))
        return await run(request, who, idempotency_key, work)

    for action, verb, says in (("done", "Mark done", "The called patient was seen."),
                               ("skip", "Skip", "The patient did not answer when called (or is skipped)."),
                               ("cancel", "Cancel", "The patient left the queue.")):
        _queue_action(api, action, verb, says)


def _queue_action(api: FastAPI, action: str, verb: str, says: str) -> None:
    @api.post(f"/queue/entries/{{entry_id}}/{action}", name=f"queue_{action}", **D.operation(
        [S.QUEUE], f"{verb} a queue entry",
        f"{says} The others' places are updated (and told). No body.\n\nTest connections: only the made-up "
        f"entries ({SAMPLE_ENTRY}<doctor id>, from check-in or GET /queue); nothing changes.",
        D.ok(200, M.QueueOut, "The doctor's queue.", None, D.IDEMPOTENT_REPLAY), [404, 409],
        {409: "Call this patient before marking them done." if action == "done" else
         "This ticket is already done."}, [D.QUEUE]))
    async def finish(request: Request, entry_id: str = Path(max_length=64), who: Caller = Depends(needs(S.QUEUE)),
                     idempotency_key: Optional[str] = IDEMPOTENCY):
        def work(session):
            if is_test(who):
                doctor = session.scalar(select(StaffUser).where(
                    StaffUser.id == entry_id[len(SAMPLE_ENTRY):], StaffUser.hospital_id == who.hospital_id,
                    StaffUser.role == Role.DOCTOR)) if entry_id.startswith(SAMPLE_ENTRY) else None
                if doctor is None:
                    raise HTTPException(status_code=404, detail="Queue entry not found.")
                status = {"done": "done", "skip": "skipped", "cancel": "cancelled"}[action]
                return 200, _sample_queue({"id": doctor.id, "full_name": doctor.full_name}, status=status)
            queue = queue_api.finish_entry(session, who.hospital_id, entry_id, action, None, via(who))
            return 200, queue_out(session, queue_api.queue_payload(session, session.get(StaffUser, queue.doctor_id),
                                                                   queue))
        return await run(request, who, idempotency_key, work)

