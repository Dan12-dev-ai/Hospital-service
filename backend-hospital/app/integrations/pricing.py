"""The hospital's price list through the integration API (docs/integrations.md,
"Pricing"): hospitals keep their prices in their own system and sync them.

* ``PUT /prices/consultation``: the in-person visit price. It is the
  hospital's ``price_in_person``, which patients see in the Endod app: a
  change is announced to the patient platform at once (app/listing.py).
* ``PUT /prices/lab-tests``, ``/prices/imaging``, ``/prices/procedures``: the
  whole list of that category, ``{code, name, price, active}`` per item. Each
  call replaces the category (items not sent are removed), so sending the same
  list again changes nothing (idempotent).
* ``GET /prices``: everything.

Scopes: ``prices.write`` to change (and read back), ``prices.read`` to read.
Prices are birr with at most two decimals (stored as santim). Changes are
audited with the connection (``via: integration``). Test connections:
everything is checked, nothing is written or announced, the answers are made
up (``"sample": true``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app import listing
from app.auth import audit
from app.db import ensure_aware, session_scope, utcnow
from app.integrations import apidoc as D, scopes as S
from app.integrations.calls import is_test, needs, run, via
from app.integrations.tokens import Caller
from app.models import Hospital, HospitalStatus, PriceCategory, PriceItem
from app.validation import Birr, birr, santim

CURRENCY = "ETB"
MAX_ITEMS = 2000
#: The path of each category, and its name in answers.
CATEGORY_PATHS = {"lab-tests": PriceCategory.LAB_TESTS, "imaging": PriceCategory.IMAGING,
                  "procedures": PriceCategory.PROCEDURES}
CATEGORY_TITLES = {PriceCategory.LAB_TESTS: "lab tests", PriceCategory.IMAGING: "imaging studies",
                   PriceCategory.PROCEDURES: "procedures"}
CODE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,39}$"


# --- models --------------------------------------------------------------------------------------------------

class ConsultationPrice(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"in_person": "150.00"}]})

    in_person: Birr = Field(gt=0, description="The in-person visit price in birr (at most two decimals), as "
                                              "patients see it in the Endod app and pay at the hospital.")


class PriceItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=CODE_PATTERN, description="Your system's code for the item (1 to 40 letters, digits, "
                                                        "`.`, `_`, `-`, `/`), unique within the category.")
    name: str = Field(min_length=2, max_length=160, description="The item's name, as patients would read it.")
    price: Birr = Field(description="Birr, at most two decimals (e.g. `\"350.00\"` or `350`).")
    active: bool = Field(default=True, description="false: kept in the list but not offered now.")

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("name must have at least 2 characters")
        return value


class PriceList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: List[PriceItemIn] = Field(max_length=MAX_ITEMS, description=f"The whole category: at most {MAX_ITEMS} "
                                                                      "items, each code once. Items not sent are "
                                                                      "removed; an empty list clears the category.")


class PriceItemOut(BaseModel):
    code: str
    name: str
    price: str = Field(description="Birr, as text with two decimals.")
    active: bool
    updated_at: Optional[str] = None


class ConsultationOut(BaseModel):
    currency: str = CURRENCY
    in_person: Optional[str] = Field(description="Birr, as text with two decimals; null until set.")
    listed: Optional[bool] = Field(default=None, description="Patients can find and book the hospital in the "
                                                             "Endod app (it also needs its location).")
    sample: Optional[bool] = Field(default=None, description="true: a Test connection's made-up answer.")


class PriceListOut(BaseModel):
    currency: str = CURRENCY
    category: str = Field(description="lab_tests, imaging or procedures.")
    items: List[PriceItemOut]
    added: int
    updated: int
    removed: int
    unchanged: int
    sample: Optional[bool] = None


class Prices(BaseModel):
    currency: str = CURRENCY
    consultation: Dict[str, Optional[str]] = Field(description="`in_person`: birr, or null until set.")
    lab_tests: List[PriceItemOut]
    imaging: List[PriceItemOut]
    procedures: List[PriceItemOut]
    sample: Optional[bool] = None


LAB_EXAMPLE = [{"code": "CBC", "name": "Complete blood count", "price": "350.00", "active": True},
               {"code": "MAL-RDT", "name": "Malaria rapid test", "price": "120.00", "active": True},
               {"code": "HBA1C", "name": "HbA1c", "price": "600.00", "active": False}]
IMAGING_EXAMPLE = [{"code": "XR-CHEST", "name": "Chest X-ray", "price": "450.00", "active": True},
                   {"code": "US-ABD", "name": "Abdominal ultrasound", "price": "800.00", "active": True},
                   {"code": "CT-HEAD", "name": "CT head without contrast", "price": "3500.00", "active": True}]
PROCEDURE_EXAMPLE = [{"code": "SUTURE-S", "name": "Wound suturing (small)", "price": "500.00", "active": True},
                     {"code": "IV-CANN", "name": "IV cannulation", "price": "150.00", "active": True}]
EXAMPLES = {PriceCategory.LAB_TESTS: LAB_EXAMPLE, PriceCategory.IMAGING: IMAGING_EXAMPLE,
            PriceCategory.PROCEDURES: PROCEDURE_EXAMPLE}
STAMP = "2026-11-03T08:00:00+00:00"


def _with_time(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{**item, "updated_at": STAMP} for item in items]


PRICES_EXAMPLE = {"currency": CURRENCY, "consultation": {"in_person": "150.00"},
                  "lab_tests": _with_time(LAB_EXAMPLE), "imaging": _with_time(IMAGING_EXAMPLE),
                  "procedures": _with_time(PROCEDURE_EXAMPLE)}


# --- reading and writing ------------------------------------------------------------------------------------

def item_out(row: PriceItem) -> Dict[str, Any]:
    return {"code": row.code, "name": row.name, "price": birr(row.price), "active": row.active,
            "updated_at": ensure_aware(row.updated_at).isoformat() if row.updated_at else None}


def rows_of(session, hospital_id: str, category: Optional[str] = None, lock: bool = False) -> List[PriceItem]:
    query = select(PriceItem).where(PriceItem.hospital_id == hospital_id)
    if category is not None:
        query = query.where(PriceItem.category == category)
    query = query.order_by(PriceItem.category, PriceItem.code)
    return list(session.scalars(query.with_for_update() if lock else query))


def price_list(session, hospital: Hospital) -> Dict[str, Any]:
    """The hospital's whole price list (also the dashboard's Settings page)."""
    rows = rows_of(session, hospital.id)
    out: Dict[str, Any] = {"currency": CURRENCY, "consultation": {"in_person": birr(hospital.price_in_person)}}
    for category in PriceCategory.ALL:
        out[category] = [item_out(r) for r in rows if r.category == category]
    return out


def _check_codes(items: List[PriceItemIn]) -> None:
    seen = set()
    for item in items:
        if item.code in seen:
            raise HTTPException(status_code=422, detail=f"The code {item.code} is in the list twice; each code once.")
        seen.add(item.code)


def replace_category(session, hospital_id: str, category: str, items: List[PriceItemIn]) -> Dict[str, int]:
    """Make the category exactly ``items``: add, update, remove (in this transaction)."""
    existing = {row.code: row for row in rows_of(session, hospital_id, category, lock=True)}
    counts = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0}
    now = utcnow()
    for item in items:
        price = santim(item.price)
        row = existing.pop(item.code, None)
        if row is None:
            session.add(PriceItem(hospital_id=hospital_id, category=category, code=item.code, name=item.name,
                                  price=price, active=item.active, created_at=now, updated_at=now))
            counts["added"] += 1
        elif (row.name, row.price, row.active) != (item.name, price, item.active):
            row.name, row.price, row.active, row.updated_at = item.name, price, item.active, now
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
    for row in existing.values():
        session.delete(row)
        counts["removed"] += 1
    session.flush()
    return counts


def _sample_item(item: PriceItemIn) -> Dict[str, Any]:
    return {"code": item.code, "name": item.name, "price": f"{item.price:.2f}", "active": item.active,
            "updated_at": None}


# --- the routes -----------------------------------------------------------------------------------------------

TEST_NOTE = "\n\nTest connections: checked as in Live, nothing is written or announced, a made-up answer."


def add_routes(api: FastAPI) -> None:
    @api.get("/prices", **D.operation(
        [S.PRICES_READ, S.PRICES_WRITE], "Read the price list",
        "The hospital's whole price list: the in-person consultation price (as patients see it) and the lab "
        "tests, imaging studies and procedures, each sorted by code. Prices are birr as text with two decimals."
        "\n\nTest connections: a made-up list (`sample: true`).",
        D.ok(200, Prices, "The price list.", PRICES_EXAMPLE), tags=[D.PRICING]))
    def read_prices(who: Caller = Depends(needs(S.PRICES_READ, S.PRICES_WRITE))) -> Dict[str, Any]:
        if is_test(who):
            return {**PRICES_EXAMPLE, "sample": True}
        with session_scope(who.hospital_id) as session:
            return price_list(session, session.get(Hospital, who.hospital_id))

    @api.put("/prices/consultation", **D.operation(
        [S.PRICES_WRITE], "Set the in-person consultation price",
        "The price of an in-person visit, in birr: what patients see when they book the hospital in the Endod app "
        "and pay at the hospital. The change is announced to the Endod app at once (the hospital is listed once "
        "it also has its location). Sending the same price again changes nothing." + TEST_NOTE,
        D.ok(200, ConsultationOut, "The price now.", {"currency": CURRENCY, "in_person": "150.00", "listed": True}),
        [400], tags=[D.PRICING]))
    async def put_consultation(request: Request,
                               body: ConsultationPrice = Body(openapi_examples={
                                   "price": {"summary": "150 birr", "value": {"in_person": "150.00"}}}),
                               who: Caller = Depends(needs(S.PRICES_WRITE))):
        def work(session):
            if is_test(who):
                return 200, {"currency": CURRENCY, "in_person": f"{body.in_person:.2f}", "listed": None,
                             "sample": True}
            hospital = session.scalar(select(Hospital).where(Hospital.id == who.hospital_id).with_for_update())
            price = santim(body.in_person)
            if hospital.price_in_person != price:
                previous = hospital.price_in_person
                hospital.price_in_person = price
                audit(session, who.hospital_id, None, "hospital_updated", "hospital", hospital.id,
                      {"fields": ["price_in_person"], "from": birr(previous), "to": birr(price), **via(who)})
                if hospital.status == HospitalStatus.APPROVED:
                    # Patients see the new price in the Endod app.
                    listing.announce(session, hospital)
            return 200, {"currency": CURRENCY, "in_person": birr(hospital.price_in_person),
                         "listed": listing.bookable(hospital)}
        return await run(request, who, None, work)

    for path, category in CATEGORY_PATHS.items():
        _category_route(api, path, category)


def _category_route(api: FastAPI, path: str, category: str) -> None:
    title = CATEGORY_TITLES[category]
    example = EXAMPLES[category]

    async def put_category(request: Request,
                           body: PriceList = Body(openapi_examples={
                               "list": {"summary": f"The whole list of {title}", "value": {"items": example}},
                               "clear": {"summary": "Remove every item", "value": {"items": []}}}),
                           who: Caller = Depends(needs(S.PRICES_WRITE))):
        _check_codes(body.items)

        def work(session):
            if is_test(who):
                return 200, {"currency": CURRENCY, "category": category,
                             "items": sorted((_sample_item(i) for i in body.items), key=lambda i: i["code"]),
                             "added": len(body.items), "updated": 0, "removed": 0, "unchanged": 0, "sample": True}
            counts = replace_category(session, who.hospital_id, category, body.items)
            if counts["added"] or counts["updated"] or counts["removed"]:
                audit(session, who.hospital_id, None, "prices_synced", "hospital", who.hospital_id,
                      {"category": category, "items": len(body.items), **counts, **via(who)})
            items = [item_out(r) for r in rows_of(session, who.hospital_id, category)]
            return 200, {"currency": CURRENCY, "category": category, "items": items, **counts}
        return await run(request, who, None, work,
                         "The price list was being changed at the same time; send it again.")

    put_category.__name__ = f"put_prices_{category}"
    api.put(f"/prices/{path}", **D.operation(
        [S.PRICES_WRITE], f"Replace the {title}",
        f"The whole list of {title}, as in your system: each item's `code` (yours, unique in the list), `name`, "
        "`price` (birr, at most two decimals) and `active`. Items with a new code are added, known codes updated, "
        "and codes not sent are removed; sending the same list again changes nothing. At most "
        f"{MAX_ITEMS} items. The answer is the list now, with what changed." + TEST_NOTE,
        D.ok(200, PriceListOut, "The list now.", {"currency": CURRENCY, "category": category,
                                                  "items": _with_time(sorted(example, key=lambda i: i["code"])),
                                                  "added": 1, "updated": 1, "removed": 0, "unchanged": 1}),
        [400, 409], {409: "The price list was being changed at the same time; send it again.",
                     422: "items.0.price: Decimal input should have no more than 2 decimal places"},
        tags=[D.PRICING]))(put_category)
