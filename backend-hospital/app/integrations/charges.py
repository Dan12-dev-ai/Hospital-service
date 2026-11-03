"""Charges through the integration API (docs/integrations.md, "Charges"):
bills for any hospital service, with Endod's service fee (app/charges.py,
app/fees.py).

* ``POST /charges``: a charge for a patient (by hospital number): items with
  their category, optional code (from your price list), name, amount (birr)
  and quantity. Endod adds its fee once per charge and answers the subtotal,
  fee and total.
* ``POST /charges/{id}/paid``: the patient paid the hospital the total (the
  hospital then owes Endod the fee). ``POST /charges/{id}/void``: an open
  charge is cancelled.
* ``GET /charges``, ``GET /charges/{id}``, ``GET /service-fee`` (the fee in force).
* ``POST /bookings/{id}/paid``: a visit booked through Endod and paid at the
  hospital (its price plus Endod's fee) was paid.

Scopes: ``charges.write`` (and reading back), ``charges.read``; bookings:
``bookings.write``. POSTs take an Idempotency-Key. Data is read and written in
a transaction of the caller's hospital (row-level security): another
hospital's charge or patient is "not found". Changes are audited with the
connection. Test connections: everything is checked, nothing is written or
sent, the answers are made up (``"sample": true``); the fee is the real one.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Path, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app import bookings as booking_rules, charges as charge_rules, fees
from app.api import bookings as bookings_api, queue as queue_api
from app.auth import audit
from app.db import session_scope
from app.integrations import apidoc as D, scopes as S
from app.integrations.calls import is_test, needs, run, via
from app.integrations.journey import IDEMPOTENCY, MRN, _doctor_names, _sample_for, booking_out, patient_by_mrn
from app.integrations import schemas as M
from app.integrations.tokens import Caller
from app.models import Booking, Charge, ChargeCategory, ChargeStatus, Patient, PaymentMethod
from app.validation import Birr, birr, santim

MAX_ITEMS = 100
CODE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,39}$"
SAMPLE_ID = "sample-charge-1"


# --- models --------------------------------------------------------------------------------------------------

class ChargeItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["lab_test", "imaging", "procedure", "consultation", "other"] = Field(
        description="What kind of service.")
    code: Optional[str] = Field(default=None, pattern=CODE_PATTERN,
                                description="Your system's code for it (e.g. from your price list, PUT /prices/...). "
                                            "Informational: not checked against the list.")
    name: str = Field(min_length=2, max_length=160, description="As the patient would read it on their bill in the "
                                                                "Endod app (never sent by SMS).")
    amount: Birr = Field(gt=0, description="The price of one, in birr (at most two decimals).")
    quantity: int = Field(default=1, ge=1, le=1000)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("name must have at least 2 characters")
        return value


class ChargeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mrn: str = Field(min_length=1, max_length=40, description="The patient's hospital number (Endod issued it).")
    items: List[ChargeItemIn] = Field(min_length=1, max_length=MAX_ITEMS,
                                      description=f"1 to {MAX_ITEMS} items: one charge, one Endod fee.")
    booking_id: Optional[str] = Field(default=None, max_length=32,
                                      description="A booking of this patient (GET /bookings) the charge belongs to.")


class ChargePaid(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["cash", "card", "mobile_money", "other"]
    reference: Optional[str] = Field(default=None, min_length=1, max_length=100,
                                     description="Your receipt or transaction number.")
    paid_at: Optional[AwareDatetime] = Field(default=None, description="When it was paid (default: now). Not in "
                                                                       "the future.")


class ChargeVoid(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=2, max_length=300, description="Why (kept with the charge; not sent to the "
                                                                  "patient).")


class ChargeItemOut(BaseModel):
    category: str
    code: Optional[str]
    name: str
    amount: str = Field(description="Birr, two decimals: one.")
    quantity: int
    line_total: str


class FeeApplied(BaseModel):
    version: int = Field(description="The version of Endod's fee settings applied (0: the default, before Endod "
                                     "sent any).")
    flat: str = Field(description="Birr.")
    percent: str = Field(description="Percent of the subtotal, e.g. `0.00`.")


CHARGE_EXAMPLE = {
    "id": "3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f", "mrn": "SPH-000124", "patient_id": "5f0c1e2d3c4b5a69788796a5b4c3d2e1",
    "endod_id": "DE482731", "booking_id": None,
    "items": [{"category": "lab_test", "code": "CBC", "name": "Complete blood count", "amount": "350.00",
               "quantity": 1, "line_total": "350.00"},
              {"category": "imaging", "code": "XR-CHEST", "name": "Chest X-ray", "amount": "450.00",
               "quantity": 1, "line_total": "450.00"}],
    "currency": "ETB", "subtotal": "800.00", "service_fee": "25.00", "total": "825.00",
    "fee": {"version": 3, "flat": "25.00", "percent": "0.00"}, "status": "open", "method": None, "reference": None,
    "paid_at": None, "void_reason": None, "voided_at": None, "fee_owed_to_endod": None,
    "created_at": "2026-11-03T08:00:00+00:00", "updated_at": "2026-11-03T08:00:00+00:00",
}
PAID_EXAMPLE = {**CHARGE_EXAMPLE, "status": "paid", "method": "cash", "reference": "RCPT-0042",
                "paid_at": "2026-11-03T09:00:00+00:00", "fee_owed_to_endod": "25.00",
                "updated_at": "2026-11-03T09:00:00+00:00"}
VOID_EXAMPLE = {**CHARGE_EXAMPLE, "status": "voided", "void_reason": "Entered twice.",
                "voided_at": "2026-11-03T08:05:00+00:00", "updated_at": "2026-11-03T08:05:00+00:00"}


class ChargeOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [CHARGE_EXAMPLE]})
    id: str
    mrn: str
    patient_id: str
    endod_id: Optional[str] = Field(description="The patient's Endod ID once linked (then they see the bill in the "
                                                "Endod app and get an SMS).")
    booking_id: Optional[str]
    items: List[ChargeItemOut]
    currency: Literal["ETB"]
    subtotal: str = Field(description="The sum of the items, birr.")
    service_fee: str = Field(description="Endod's service fee, birr: one per charge, paid by the patient.")
    total: str = Field(description="What the patient pays the hospital, birr.")
    fee: FeeApplied
    status: Literal["open", "paid", "voided"]
    method: Optional[str]
    reference: Optional[str]
    paid_at: Optional[str]
    void_reason: Optional[str]
    voided_at: Optional[str]
    fee_owed_to_endod: Optional[str] = Field(description="Once paid: the fee the hospital collected for Endod.")
    created_at: str
    updated_at: str
    sample: Optional[bool] = Field(default=None, description="Test connections only: a made-up answer.")


class ChargeList(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"items": [CHARGE_EXAMPLE]}]})
    items: List[ChargeOut]


FEE_EXAMPLE = {"currency": "ETB", "enabled": True, "flat": "25.00", "percent": "0.00",
               "rule": "one fee per charge or booking: flat + percent of the subtotal, rounded to the santim; none on 0",
               "example": {"subtotal": "200.00", "service_fee": "25.00", "total": "225.00"},
               "updated_at": "2026-11-03T08:00:00+00:00"}


class ServiceFee(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [FEE_EXAMPLE]})
    currency: Literal["ETB"]
    enabled: bool
    flat: str = Field(description="Birr per charge or booking.")
    percent: str = Field(description="Percent of the subtotal.")
    rule: str
    example: Dict[str, str] = Field(description="What a 200 birr bill becomes.")
    updated_at: Optional[str] = Field(description="When Endod last changed it (null: the default).")


# --- helpers -------------------------------------------------------------------------------------------------

def _items(body: ChargeCreate) -> List[Dict[str, Any]]:
    return [{"category": i.category, **({"code": i.code} if i.code else {}), "name": i.name,
             "amount": santim(i.amount), "quantity": i.quantity} for i in body.items]


def _sample(mrn: str, items: List[Dict[str, Any]], fee: fees.Fee, status: str = "open") -> Dict[str, Any]:
    amounts = charge_rules.totals(items, fee)
    now = datetime.now(timezone.utc).isoformat()
    out = {**CHARGE_EXAMPLE, "id": SAMPLE_ID, "mrn": mrn, "patient_id": "sample-patient", "endod_id": None,
           "items": charge_rules.items_out(items), "subtotal": birr(amounts["subtotal"]),
           "service_fee": birr(amounts["service_fee"]), "total": birr(amounts["total"]),
           "fee": {"version": fee.version, "flat": birr(fee.flat_santim if fee.enabled else 0),
                   "percent": f"{(fee.percent_bp if fee.enabled else 0) / 100:.2f}"},
           "status": status, "created_at": now, "updated_at": now, "sample": True}
    if status == "paid":
        out.update(method="cash", paid_at=now, fee_owed_to_endod=out["service_fee"])
    if status == "voided":
        out.update(void_reason="Sample.", voided_at=now)
    return out


SAMPLE_ITEMS = [{"category": "lab_test", "code": "CBC", "name": "Complete blood count", "amount": 35000, "quantity": 1}]


def _charge(session, hospital_id: str, charge_id: str, lock: bool = False) -> Charge:
    query = select(Charge).where(Charge.id == charge_id, Charge.hospital_id == hospital_id)
    charge = session.scalar(query.with_for_update() if lock else query)
    if charge is None:
        raise HTTPException(status_code=404, detail="Charge not found.")
    return charge


def _rules(call):
    try:
        return call()
    except (charge_rules.ChargeError, booking_rules.BookingError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


TEST_NOTE = "\n\nTest connections: checked as in Live, nothing is written or sent, a made-up answer (`sample: true`)."


def add_routes(api: FastAPI) -> None:  # noqa: C901 -- one place lists every charge endpoint
    @api.get("/service-fee", **D.operation(
        [S.CHARGES_READ, S.CHARGES_WRITE, S.BOOKINGS_READ], "Read Endod's service fee",
        "The service fee Endod adds now: once per charge and per paid booking, paid by the patient (never by the "
        "hospital). Endod sets it; this is the last setting Endod sent (it still applies while Endod is "
        "unreachable).",
        D.ok(200, ServiceFee, "The fee now.", FEE_EXAMPLE), tags=[D.CHARGES]))
    def read_fee(who: Caller = Depends(needs(S.CHARGES_READ, S.CHARGES_WRITE, S.BOOKINGS_READ))) -> Dict[str, Any]:
        with session_scope(who.hospital_id) as session:
            return fees.describe(fees.current(session))

    @api.post("/charges", status_code=201, **D.operation(
        [S.CHARGES_WRITE], "Charge a patient",
        "A bill for one or more hospital services (lab tests, imaging, procedures, a consultation, anything else) "
        "for a registered patient. Endod computes the subtotal (amount x quantity, to the santim), adds its "
        "service fee **once per charge** (GET /service-fee) and answers the total the patient pays. A patient "
        "linked to Endod sees the bill in the Endod app and gets an SMS with the amount only (never what it is "
        "for). Webhook `charge.created`. The patient pays at the hospital: then POST /charges/{id}/paid." + TEST_NOTE,
        D.ok(201, ChargeOut, "The charge, with its total.", CHARGE_EXAMPLE, D.IDEMPOTENT_REPLAY), [400, 404, 409],
        {400: "A charge must be for more than 0 birr.", 409: "This booking is not this patient's."},
        tags=[D.CHARGES]))
    async def create_charge(request: Request,
                            body: ChargeCreate = Body(openapi_examples={
                                "lab_and_imaging": {"summary": "Two items, one fee", "value": {
                                    "mrn": "SPH-000124", "items": [
                                        {"category": "lab_test", "code": "CBC", "name": "Complete blood count",
                                         "amount": "350.00", "quantity": 1},
                                        {"category": "imaging", "code": "XR-CHEST", "name": "Chest X-ray",
                                         "amount": "450.00", "quantity": 1}]}},
                                "for_a_booking": {"summary": "A procedure during a booked visit", "value": {
                                    "mrn": "SPH-000124", "booking_id": "9f0c2b7a1e4d4f6a8b3c5d7e9f1a2b4c",
                                    "items": [{"category": "procedure", "name": "Wound dressing", "amount": "120",
                                               "quantity": 2}]}}}),
                            who: Caller = Depends(needs(S.CHARGES_WRITE)),
                            idempotency_key: Optional[str] = IDEMPOTENCY):
        items = _items(body)

        def work(session):
            fee = fees.current(session)
            if charge_rules.totals(items, fee)["subtotal"] <= 0:
                raise HTTPException(status_code=400, detail="A charge must be for more than 0 birr.")
            if is_test(who):
                return 201, _sample(body.mrn.strip().upper(), items, fee)
            patient = patient_by_mrn(session, who.hospital_id, body.mrn, lock=True)
            booking = None
            if body.booking_id:
                booking = session.scalar(select(Booking).where(Booking.id == body.booking_id,
                                                               Booking.hospital_id == who.hospital_id))
                if booking is None:
                    raise HTTPException(status_code=404, detail="Booking not found.")
                if not queue_api.same_person(patient, booking, queue_api._booking_dedan(booking)):
                    raise HTTPException(status_code=409, detail="This booking is not this patient's (Endod ID or "
                                                                "phone number).")
            charge = _rules(lambda: charge_rules.create(session, who.hospital_id, patient, items, booking, via(who)))
            return 201, charge_rules.charge_out(charge, patient)
        return await run(request, who, idempotency_key, work)

    @api.get("/charges", **D.operation(
        [S.CHARGES_READ, S.CHARGES_WRITE], "List charges",
        "Charges, newest first, optionally of one patient, one status or a period (created at or after `from`, "
        "before `to`).\n\nTest connections: a made-up charge.",
        D.ok(200, ChargeList, "The charges.", {"items": [CHARGE_EXAMPLE]}), [400, 404], tags=[D.CHARGES]))
    def list_charges(status: Optional[str] = Query(default=None, description=f"One of {list(ChargeStatus.ALL)}."),
                     mrn: Optional[str] = Query(default=None, max_length=40),
                     created_from: Optional[AwareDatetime] = Query(default=None, alias="from"),
                     created_to: Optional[AwareDatetime] = Query(default=None, alias="to"),
                     limit: int = Query(default=100, ge=1, le=500),
                     who: Caller = Depends(needs(S.CHARGES_READ, S.CHARGES_WRITE))) -> Dict[str, Any]:
        if status is not None and status not in ChargeStatus.ALL:
            raise HTTPException(status_code=400, detail=f"status must be one of {list(ChargeStatus.ALL)}.")
        if is_test(who):
            with session_scope(who.hospital_id) as session:
                sample = _sample((mrn or "TEST-000001").strip().upper(), SAMPLE_ITEMS, fees.current(session))
            return {"items": [sample] if status in (None, "open") else []}
        with session_scope(who.hospital_id) as session:
            query = select(Charge).where(Charge.hospital_id == who.hospital_id)
            if mrn:
                query = query.where(Charge.patient_id == patient_by_mrn(session, who.hospital_id, mrn).id)
            if status:
                query = query.where(Charge.status == status)
            if created_from:
                query = query.where(Charge.created_at >= created_from)
            if created_to:
                query = query.where(Charge.created_at < created_to)
            rows = list(session.scalars(query.order_by(Charge.created_at.desc(), Charge.id).limit(limit)))
            patients = {p.id: p for p in session.scalars(select(Patient).where(
                Patient.id.in_({r.patient_id for r in rows})))} if rows else {}
            return {"items": [charge_rules.charge_out(r, patients[r.patient_id]) for r in rows]}

    @api.get("/charges/{charge_id}", **D.operation(
        [S.CHARGES_READ, S.CHARGES_WRITE], "Read a charge",
        "One charge with its items (another hospital's is never found).\n\nTest connections: only the made-up "
        f"charge (`{SAMPLE_ID}`).",
        D.ok(200, ChargeOut, "The charge.", CHARGE_EXAMPLE), [404], tags=[D.CHARGES]))
    def read_charge(charge_id: str = Path(max_length=32),
                    who: Caller = Depends(needs(S.CHARGES_READ, S.CHARGES_WRITE))) -> Dict[str, Any]:
        with session_scope(who.hospital_id) as session:
            if is_test(who):
                if charge_id != SAMPLE_ID:
                    raise HTTPException(status_code=404, detail="Charge not found.")
                return _sample("TEST-000001", SAMPLE_ITEMS, fees.current(session))
            charge = _charge(session, who.hospital_id, charge_id)
            return charge_rules.charge_out(charge, session.get(Patient, charge.patient_id))

    paid_examples = {"cash": {"summary": "Paid in cash", "value": {"method": "cash", "reference": "RCPT-0042"}},
                     "mobile": {"summary": "Paid by telebirr, earlier", "value": {
                         "method": "mobile_money", "reference": "TB7781234", "paid_at": "2026-11-03T09:00:00+03:00"}}}

    @api.post("/charges/{charge_id}/paid", **D.operation(
        [S.CHARGES_WRITE], "Mark a charge paid at the hospital",
        "The patient paid the hospital the charge's `total`: the hospital collected Endod's service fee with it "
        "and owes it to Endod (`fee_owed_to_endod`; Endod settles fees with the hospital). The patient's bill in "
        "the Endod app shows it paid. Webhook `charge.paid`. Sending it again with the same method changes "
        "nothing; a voided charge cannot be paid (409)." + TEST_NOTE,
        D.ok(200, ChargeOut, "The charge, paid.", PAID_EXAMPLE, D.IDEMPOTENT_REPLAY), [400, 404, 409],
        {409: "This charge was voided; it cannot be paid."}, tags=[D.CHARGES]))
    async def pay_charge(request: Request, charge_id: str = Path(max_length=32),
                         body: ChargePaid = Body(openapi_examples=paid_examples),
                         who: Caller = Depends(needs(S.CHARGES_WRITE)),
                         idempotency_key: Optional[str] = IDEMPOTENCY):
        def work(session):
            if is_test(who):
                if charge_id != SAMPLE_ID:
                    raise HTTPException(status_code=404, detail="Charge not found.")
                return 200, _sample("TEST-000001", SAMPLE_ITEMS, fees.current(session), "paid")
            charge = _charge(session, who.hospital_id, charge_id, lock=True)
            patient = session.get(Patient, charge.patient_id)
            _rules(lambda: charge_rules.mark_paid(session, charge, patient, body.method, body.reference,
                                                  body.paid_at, via(who)))
            return 200, charge_rules.charge_out(charge, patient)
        return await run(request, who, idempotency_key, work)

    @api.post("/charges/{charge_id}/void", **D.operation(
        [S.CHARGES_WRITE], "Void a charge",
        "An open charge is cancelled (made by mistake, or the service was not given); the patient's bill in the "
        "Endod app shows it cancelled. A paid charge cannot be voided (409). Webhook `charge.voided`." + TEST_NOTE,
        D.ok(200, ChargeOut, "The charge, voided.", VOID_EXAMPLE, D.IDEMPOTENT_REPLAY), [404, 409],
        {409: "A paid charge cannot be voided."}, tags=[D.CHARGES]))
    async def void_charge(request: Request, charge_id: str = Path(max_length=32),
                          body: ChargeVoid = Body(openapi_examples={
                              "mistake": {"summary": "Entered twice", "value": {"reason": "Entered twice."}}}),
                          who: Caller = Depends(needs(S.CHARGES_WRITE)),
                          idempotency_key: Optional[str] = IDEMPOTENCY):
        def work(session):
            if is_test(who):
                if charge_id != SAMPLE_ID:
                    raise HTTPException(status_code=404, detail="Charge not found.")
                return 200, _sample("TEST-000001", SAMPLE_ITEMS, fees.current(session), "voided")
            charge = _charge(session, who.hospital_id, charge_id, lock=True)
            patient = session.get(Patient, charge.patient_id)
            _rules(lambda: charge_rules.void(session, charge, patient, body.reason.strip(), via(who)))
            return 200, charge_rules.charge_out(charge, patient)
        return await run(request, who, idempotency_key, work)

    @api.post("/bookings/{booking_id}/paid", **D.operation(
        [S.BOOKINGS_WRITE], "Mark a visit paid at the hospital",
        "A booking with `payment: at_hospital` was paid: the patient paid its `total` (the price plus Endod's "
        "service fee), and the hospital owes Endod the fee (`fee_owed_to_endod`). A visit completed without this "
        "counts as paid when completed. Only a confirmed or completed visit paid at the hospital (409 otherwise)."
        "\n\nTest connections: tried with the same rules on the made-up bookings of GET /bookings; nothing "
        "changes and nothing is sent.",
        D.ok(200, M.BookingOut, "The booking, paid.", {**M.BOOKING_EXAMPLE, "payment": "at_hospital",
                                                      "paid_at": "2026-10-02T07:10:00+00:00", "paid_method": "cash"},
             D.IDEMPOTENT_REPLAY),
        [400, 404, 409], {409: "Only a priced visit paid at the hospital is marked paid here."}, tags=[D.BOOKINGS]))
    async def pay_booking(request: Request, booking_id: str = Path(max_length=32),
                          body: ChargePaid = Body(openapi_examples=paid_examples),
                          who: Caller = Depends(needs(S.BOOKINGS_WRITE)),
                          idempotency_key: Optional[str] = IDEMPOTENCY):
        def action(session, booking):
            _rules(lambda: booking_rules.mark_paid(session, booking, body.method, body.reference, body.paid_at))

        def work(session):
            if is_test(who):
                booking = _sample_for(booking_id, who.hospital_id)
                savepoint = session.begin_nested()
                try:
                    action(session, booking)
                finally:
                    savepoint.rollback()
                return 200, {**booking_out(booking, {}), "sample": True}
            booking = bookings_api.booking_for_update(session, who.hospital_id, booking_id)
            action(session, booking)
            audit(session, who.hospital_id, None, "booking_paid", "booking", booking.id,
                  {"method": body.method, **via(who)})
            session.flush()
            return 200, booking_out(booking, _doctor_names(session, [booking.doctor_id]))
        return await run(request, who, idempotency_key, work)
