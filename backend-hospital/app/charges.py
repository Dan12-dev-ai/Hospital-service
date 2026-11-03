"""Charges: bills for hospital services (lab tests, imaging, procedures,
consultations, anything else), with Endod's service fee (docs/integrations.md
"Charges"; the platform's docs/service-fee.md).

The hospital's own system makes a charge through the integration API
(app/integrations/charges.py). Here:

* :func:`create`: the subtotal (sum of amount x quantity, santim), Endod's fee
  once per charge (app/fees.py: the settings in force, kept on the charge),
  the total. The patient's app gets the bill (``charge.created`` to the
  platform, only for a patient linked to Endod); the hospital's systems get
  the ``charge.created`` webhook.
* :func:`mark_paid`: the patient paid the hospital the total, so the hospital
  owes Endod the fee: ``charge.paid`` to the platform (every charge: Endod's
  fee ledger) and the webhook.
* :func:`void`: an open charge is cancelled (``charge.voided``). A paid one
  cannot be voided.

Every change is audited with the connection (``via: integration``). Events
and webhooks never carry the items (what was done): the platform's bill gets
them (``charge.created``, linked patients only, encrypted at rest there).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app import eventbus, fees
from app.auth import audit
from app.db import ensure_aware, utcnow
from app.integrations import webhooks
from app.models import Booking, Charge, ChargeStatus, Patient
from app.validation import birr

CURRENCY = "ETB"


class ChargeError(RuntimeError):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def totals(items: List[Dict[str, Any]], fee: fees.Fee) -> Dict[str, int]:
    """Subtotal, Endod's fee and total, in santim (items' ``amount`` in santim)."""
    subtotal = sum(int(i["amount"]) * int(i["quantity"]) for i in items)
    service_fee = fees.fee_for(subtotal, fee)
    return {"subtotal": subtotal, "service_fee": service_fee, "total": subtotal + service_fee}


def _iso(value: Optional[datetime]) -> Optional[str]:
    return ensure_aware(value).isoformat() if value else None


def items_out(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"category": i["category"], "code": i.get("code"), "name": i["name"], "amount": birr(i["amount"]),
             "quantity": i["quantity"], "line_total": birr(i["amount"] * i["quantity"])} for i in items]


def charge_out(charge: Charge, patient: Patient) -> Dict[str, Any]:
    items = json.loads(charge.items or "[]")
    return {
        "id": charge.id, "mrn": patient.mrn, "patient_id": patient.id, "endod_id": patient.dedan_id,
        "booking_id": charge.booking_id, "items": items_out(items), "currency": charge.currency,
        "subtotal": birr(charge.subtotal), "service_fee": birr(charge.service_fee), "total": birr(charge.total),
        "fee": {"version": charge.fee_version, "flat": birr(charge.fee_flat_santim),
                "percent": f"{charge.fee_percent_bp / 100:.2f}"},
        "status": charge.status, "method": charge.method, "reference": charge.reference,
        "paid_at": _iso(charge.paid_at), "void_reason": charge.void_reason, "voided_at": _iso(charge.voided_at),
        # Paid at the hospital: the hospital collected the total and owes Endod the fee.
        "fee_owed_to_endod": birr(charge.service_fee) if charge.status == ChargeStatus.PAID else None,
        "created_at": _iso(charge.created_at), "updated_at": _iso(charge.updated_at),
    }


def _amounts(charge: Charge) -> Dict[str, Any]:
    return {"subtotal": charge.subtotal, "service_fee": charge.service_fee, "total": charge.total,
            "currency": charge.currency}


def _platform_ids(charge: Charge, patient: Patient, booking: Optional[Booking]) -> Dict[str, Any]:
    return {"charge_id": charge.id, "hospital_id": charge.hospital_id, "dedan_id": patient.dedan_id,
            "appointment_id": booking.external_id if booking is not None else None}


def _webhook(session: Session, charge: Charge, patient: Patient, event_type: str) -> None:
    session.flush()
    webhooks.emit(session, charge.hospital_id, event_type, {
        "charge_id": charge.id, "patient_id": patient.id, "mrn": patient.mrn, "endod_id": patient.dedan_id,
        "booking_id": charge.booking_id, "status": charge.status, "currency": charge.currency,
        "subtotal": birr(charge.subtotal), "service_fee": birr(charge.service_fee), "total": birr(charge.total),
        "method": charge.method, "paid_at": _iso(charge.paid_at)})


def create(session: Session, hospital_id: str, patient: Patient, items: List[Dict[str, Any]],
           booking: Optional[Booking], via: Dict[str, Any]) -> Charge:
    fee = fees.current(session)
    amounts = totals(items, fee)
    if amounts["subtotal"] <= 0:
        raise ChargeError("A charge must be for more than 0 birr.", 400)
    now = utcnow()
    charge = Charge(hospital_id=hospital_id, patient_id=patient.id, booking_id=booking.id if booking else None,
                    items=json.dumps(items, ensure_ascii=False), currency=CURRENCY, fee_version=fee.version,
                    fee_flat_santim=fee.flat_santim if fee.enabled else 0,
                    fee_percent_bp=fee.percent_bp if fee.enabled else 0, status=ChargeStatus.OPEN,
                    client_id=via.get("client_id"), created_at=now, updated_at=now, **amounts)
    session.add(charge)
    session.flush()
    audit(session, hospital_id, None, "charge_created", "patient", patient.id,
          {"charge_id": charge.id, "items": len(items), "subtotal": birr(charge.subtotal),
           "service_fee": birr(charge.service_fee), "total": birr(charge.total), **via})
    if patient.dedan_id:
        # The patient's bill in the Endod app (and a text: the amount only).
        eventbus.emit(session, "charge.created", {**_platform_ids(charge, patient, booking), "items": items,
                                                  **_amounts(charge)})
    _webhook(session, charge, patient, "charge.created")
    return charge


def mark_paid(session: Session, charge: Charge, patient: Patient, method: str, reference: Optional[str],
              paid_at: Optional[datetime], via: Dict[str, Any]) -> bool:
    """Returns False when it was already paid the same way (nothing changes)."""
    if charge.status == ChargeStatus.VOIDED:
        raise ChargeError("This charge was voided; it cannot be paid.")
    if charge.status == ChargeStatus.PAID:
        if charge.method == method and (reference is None or reference == charge.reference):
            return False
        raise ChargeError("This charge is already paid.")
    when = (paid_at or utcnow()).astimezone(timezone.utc)
    if when > utcnow() + timedelta(minutes=5):
        raise ChargeError("paid_at cannot be in the future.", 400)
    if when < ensure_aware(charge.created_at) - timedelta(days=1):
        raise ChargeError("paid_at cannot be before the charge was made.", 400)
    charge.status, charge.method, charge.reference = ChargeStatus.PAID, method, reference
    charge.paid_at, charge.updated_at = when, utcnow()
    audit(session, charge.hospital_id, None, "charge_paid", "patient", patient.id,
          {"charge_id": charge.id, "method": method, "total": birr(charge.total),
           "fee_owed_to_endod": birr(charge.service_fee), **via})
    booking = session.get(Booking, charge.booking_id) if charge.booking_id else None
    # Every charge (linked patient or not): Endod's fee ledger.
    eventbus.emit(session, "charge.paid", {**_platform_ids(charge, patient, booking), **_amounts(charge),
                                           "method": method, "reference": reference, "paid_at": when.isoformat()})
    _webhook(session, charge, patient, "charge.paid")
    return True


def void(session: Session, charge: Charge, patient: Patient, reason: str, via: Dict[str, Any]) -> bool:
    if charge.status == ChargeStatus.PAID:
        raise ChargeError("A paid charge cannot be voided.")
    if charge.status == ChargeStatus.VOIDED:
        return False
    charge.status, charge.void_reason = ChargeStatus.VOIDED, reason
    charge.voided_at = charge.updated_at = utcnow()
    audit(session, charge.hospital_id, None, "charge_voided", "patient", patient.id,
          {"charge_id": charge.id, **via})
    if patient.dedan_id:
        eventbus.emit(session, "charge.voided", {"charge_id": charge.id, "hospital_id": charge.hospital_id,
                                                 "dedan_id": patient.dedan_id})
    _webhook(session, charge, patient, "charge.voided")
    return True
