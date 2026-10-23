"""Prescriptions dispensed at pharmacies (docs/pharmacy.md, section 4).

When a pharmacy gives medicine from one of this hospital's prescriptions,
Endod sends ``prescription.dispensed``. It is stored once per
``dispense_id`` and shown on the prescription record in the portal.
"""

from __future__ import annotations

import json
import re
from datetime import timezone
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import ensure_aware
from app.eventbus import PermanentEventError, RetryLater
from app.models import ClinicalRecord, Hospital, PrescriptionDispense, RecordCategory
from app.records import iso
from app.validation import normalize_dedan_id

#: A prescription has at most 30 items (app.records.Prescription).
MAX_ITEMS = 30
#: The most of one item a pharmacy can report (a sanity bound, not a rule).
MAX_AMOUNT = 1_000_000

Number = Union[int, float]


def _whole(value: Optional[float]) -> Optional[Number]:
    """14.0 -> 14 (counts are usually whole)."""
    if value is None:
        return None
    return int(value) if float(value).is_integer() else value


class _Item(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item_index: int = Field(ge=0, lt=MAX_ITEMS)
    amount: Optional[float] = Field(default=None, ge=0, le=MAX_AMOUNT, allow_inf_nan=False)
    complete: bool
    given_total: Optional[float] = Field(default=None, ge=0, le=MAX_AMOUNT, allow_inf_nan=False)
    status: Literal["not_given", "partly_given", "given"]


class Dispensed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    hospital_id: str = Field(min_length=1, max_length=32)
    dedan_id: str = Field(min_length=1, max_length=16)
    dispense_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    at: AwareDatetime
    pharmacy_name: str = Field(min_length=2, max_length=120)
    status: Literal["open", "completed"]
    items: List[_Item] = Field(min_length=1, max_length=MAX_ITEMS)

    @field_validator("pharmacy_name", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("items")
    @classmethod
    def _distinct(cls, items: List[_Item]) -> List[_Item]:
        if len({i.item_index for i in items}) != len(items):
            raise ValueError("an item_index appears twice")
        return items


def _parse(payload: Dict[str, Any]) -> Dispensed:
    try:
        return Dispensed.model_validate(payload)
    except ValidationError as exc:
        raise PermanentEventError(str(exc).splitlines()[0]) from exc


def on_dispensed(session: Session, payload: Dict[str, Any]) -> None:
    event = _parse(payload)
    try:
        dedan_id = normalize_dedan_id(event.dedan_id)
    except ValueError as exc:
        raise PermanentEventError(str(exc)) from exc
    if session.get(Hospital, event.hospital_id) is None:
        raise PermanentEventError("unknown hospital")
    existing = session.get(PrescriptionDispense, event.dispense_id)
    if existing is not None:
        if (existing.record_id, existing.hospital_id) != (event.record_id, event.hospital_id):
            raise PermanentEventError("dispense_id already used for another prescription")
        return  # a redelivery, or the same dispense sent again: stored once
    record = session.get(ClinicalRecord, event.record_id)
    if record is None:
        # Records are made here: Endod cannot know one that does not exist,
        # unless it was deleted (with its patient). Retried, then dead-lettered.
        raise RetryLater(f"record {event.record_id} not found")
    if record.hospital_id != event.hospital_id:
        raise PermanentEventError("the record belongs to another hospital")
    if record.category != RecordCategory.PRESCRIPTION:
        raise PermanentEventError(f"the record is a {record.category}, not a prescription")
    if record.published_dedan_id != dedan_id:
        raise PermanentEventError("the record was not sent to this Endod account")
    session.add(PrescriptionDispense(
        id=event.dispense_id, hospital_id=event.hospital_id, record_id=record.id, dedan_id=dedan_id,
        pharmacy_name=event.pharmacy_name, dispensed_at=event.at.astimezone(timezone.utc), status=event.status,
        items=json.dumps([{"item_index": i.item_index, "amount": _whole(i.amount), "complete": i.complete,
                           "given_total": _whole(i.given_total), "status": i.status} for i in event.items]),
    ))


HANDLERS = {
    "prescription.dispensed": on_dispensed,
}


# --- what the portal shows ------------------------------------------------------------------

_LEADING_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)?)")


def quantity_total(text: Optional[str]) -> Optional[Number]:
    """The leading number of the quantity as written ("21 tablets" -> 21), as
    the platform counts it (docs/pharmacy.md, section 1); None otherwise."""
    match = _LEADING_NUMBER.match(text or "")
    return _whole(float(match.group(1))) if match else None


def dispenses_of(session: Session, record_ids: List[str]) -> Dict[str, List[PrescriptionDispense]]:
    """Each record's dispenses, oldest first."""
    out: Dict[str, List[PrescriptionDispense]] = {}
    if not record_ids:
        return out
    for d in session.scalars(select(PrescriptionDispense).where(PrescriptionDispense.record_id.in_(record_ids))
                             .order_by(PrescriptionDispense.dispensed_at, PrescriptionDispense.received_at,
                                       PrescriptionDispense.id)):
        out.setdefault(d.record_id, []).append(d)
    return out


def dispensing_payload(record: ClinicalRecord, dispenses: List[PrescriptionDispense]) -> Dict[str, Any]:
    """``status``: not_dispensed, partly or fully; and each dispense, with
    every item's drug and total (from the record as it is now)."""
    try:
        written = json.loads(record.details).get("items") or []
    except (ValueError, AttributeError):
        written = []
    if not dispenses:
        status = "not_dispensed"
    elif any(d.status == "completed" for d in dispenses):
        status = "fully"
    else:
        status = "partly"
    shown = []
    for d in dispenses:
        items = []
        for item in json.loads(d.items):
            index = item["item_index"]
            source = written[index] if index < len(written) and isinstance(written[index], dict) else {}
            items.append({**item, "drug": source.get("drug"), "quantity_total": quantity_total(source.get("quantity"))})
        shown.append({"dispense_id": d.id, "at": iso(ensure_aware(d.dispensed_at)), "pharmacy_name": d.pharmacy_name,
                      "status": d.status, "items": items})
    return {"status": status, "dispenses": shown}
