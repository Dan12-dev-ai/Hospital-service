"""Hospitals join Endod: sign-up through the portal, approval by Endod.

* ``POST /onboarding`` (public): a hospital creates its account and its first
  admin, and is signed in. It starts as *pending*: the portal works, but
  patients do not see it until Endod approves it.
* ``/platform/hospitals...`` (Endod only, ``X-Platform-Key``): list hospitals,
  approve or suspend them. Approving announces the hospital to the patient
  app once its listing is complete (a price and a location).
"""

from __future__ import annotations

import hmac
import re
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import auth, listing
from app.api.admin import hospital_payload
from app.auth import audit
from app.config import get_settings
from app.db import session_scope, utcnow
from app.models import Hospital, HospitalKind, HospitalStatus, Role, StaffUser
from app.security import hash_password, password_problem
from app.validation import ContactNumber, Name, OptionalText

router = APIRouter(tags=["onboarding"])

#: Sign-ups per address per hour (a hospital signs up once).
SIGNUPS_PER_HOUR = 5
_signups: Dict[str, Deque[float]] = {}
_signups_lock = threading.Lock()


class HospitalSignup(BaseModel):
    hospital_name: Name = Field(max_length=160)
    hospital_name_am: OptionalText = Field(default=None, max_length=160)
    kind: str
    city: Name = Field(max_length=100)
    phone: ContactNumber = None
    admin_name: Name = Field(max_length=120)
    admin_email: EmailStr
    password: str = Field(min_length=1, max_length=200)


def _rate_limited(key: str) -> bool:
    now = time.monotonic()
    with _signups_lock:
        hits = _signups.setdefault(key, deque())
        while hits and hits[0] < now - 3600:
            hits.popleft()
        if len(hits) >= SIGNUPS_PER_HOUR:
            return True
        hits.append(now)
        if len(_signups) > 10_000:
            _signups.clear()
        return False


def _code_for(session, name: str) -> str:
    """A short unique code from the name's initials (used in hospital numbers), e.g. TASH."""
    words = [w for w in re.findall(r"[A-Za-z]+", name) if w.lower() not in {"of", "the", "and"}]
    base = "".join(w[0] for w in words).upper()[:6] or "HOSP"
    if len(base) < 2:
        base = (re.sub(r"[^A-Za-z]", "", name).upper() + "XX")[:3]
    taken = set(session.scalars(select(Hospital.code).where(Hospital.code.like(f"{base}%"))))
    if base not in taken:
        return base
    for n in range(2, 1000):
        if f"{base}{n}" not in taken:
            return f"{base}{n}"
    raise HTTPException(status_code=409, detail="Could not choose a hospital code; contact Endod.")


@router.post("/onboarding", status_code=status.HTTP_201_CREATED)
def sign_up(body: HospitalSignup, request: Request) -> Dict[str, Any]:
    settings = get_settings()
    if not settings.SIGNUP_ENABLED:
        raise HTTPException(status_code=403, detail="Sign-up is closed. Contact Endod to join.")
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    if _rate_limited(forwarded or (request.client.host if request.client else "unknown")):
        raise HTTPException(status_code=429, detail="Too many sign-ups from here. Try again later.")
    if body.kind not in HospitalKind.ALL:
        raise HTTPException(status_code=400, detail=f"kind must be one of {list(HospitalKind.ALL)}.")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    email = body.admin_email.lower()
    try:
        with session_scope() as session:
            hospital = Hospital(
                code=_code_for(session, body.hospital_name), name=body.hospital_name,
                name_am=body.hospital_name_am, kind=body.kind, city=body.city, phone=body.phone,
                status=HospitalStatus.PENDING, timezone=settings.DEFAULT_TIMEZONE,
            )
            session.add(hospital)
            session.flush()
            admin = StaffUser(
                hospital_id=hospital.id, email=email, full_name=body.admin_name, role=Role.ADMIN,
                password_hash=hash_password(body.password), must_change_password=False,
            )
            session.add(admin)
            session.flush()
            audit(session, hospital.id, admin.id, "hospital_signed_up", "hospital", hospital.id)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="This email cannot be used for a new account.") from exc
    signed_in = auth.login(email, body.password, request.headers.get("user-agent"))
    return {**signed_in, "hospital": hospital_payload_by_id(signed_in["staff"]["hospital"]["id"])}


def hospital_payload_by_id(hospital_id: str) -> Dict[str, Any]:
    with session_scope() as session:
        return hospital_payload(session.get(Hospital, hospital_id))


# --- Endod platform admin ---------------------------------------------------------------

def platform_admin(x_platform_key: Optional[str] = Header(default=None)) -> None:
    key = get_settings().PLATFORM_ADMIN_KEY
    if not key:
        raise HTTPException(status_code=404, detail="Not found.")
    if not x_platform_key or not hmac.compare_digest(x_platform_key.encode(), key.encode()):
        raise HTTPException(status_code=401, detail="Authentication required.")


@router.get("/platform/hospitals", dependencies=[Depends(platform_admin)])
def list_hospitals(status_filter: Optional[str] = Query(default=None, alias="status")) -> List[Dict[str, Any]]:
    if status_filter is not None and status_filter not in HospitalStatus.ALL:
        raise HTTPException(status_code=400, detail=f"status must be one of {list(HospitalStatus.ALL)}.")
    with session_scope() as session:
        query = select(Hospital).order_by(Hospital.created_at.desc())
        if status_filter:
            query = query.where(Hospital.status == status_filter)
        return [hospital_payload(h) for h in session.scalars(query)]


def set_status(hospital_id: str, new_status: str) -> Dict[str, Any]:
    """Approve or suspend a hospital, and update the patient app's listing."""
    with session_scope() as session:
        hospital = session.scalar(select(Hospital).where(Hospital.id == hospital_id).with_for_update())
        if hospital is None:
            raise HTTPException(status_code=404, detail="Hospital not found.")
        hospital.status = new_status
        if new_status == HospitalStatus.APPROVED and hospital.approved_at is None:
            hospital.approved_at = utcnow()
        audit(session, hospital.id, None, f"hospital_{new_status}", "hospital", hospital.id)
        listing.announce(session, hospital)
        session.flush()
        return hospital_payload(hospital)


@router.post("/platform/hospitals/{hospital_id}/approve", dependencies=[Depends(platform_admin)])
def approve(hospital_id: str) -> Dict[str, Any]:
    return set_status(hospital_id, HospitalStatus.APPROVED)


@router.post("/platform/hospitals/{hospital_id}/suspend", dependencies=[Depends(platform_admin)])
def suspend(hospital_id: str) -> Dict[str, Any]:
    return set_status(hospital_id, HospitalStatus.SUSPENDED)
