"""Hospitals join Endod: sign-up through the portal, approval by Endod.

* ``POST /onboarding`` (public): a hospital creates its account and its first
  admin (the contact person), and is signed in. It starts as *pending*: it
  can only fill in its application (app.api.application) until Endod approves
  it; every other staff route answers 403 (app.auth.current_staff).
* ``/platform/hospitals...`` (Endod only, ``X-Platform-Key``): list hospitals,
  approve, reject (app.api.application) or suspend them. Approving announces
  the hospital to the patient app once its listing is complete (a price and a
  location).
"""

from __future__ import annotations

import hmac
import re
import threading
import time
from collections import OrderedDict, deque
from typing import Any, Deque, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import auth, files, listing, onboarding
from app.api.admin import hospital_payload
from app.auth import audit
from app.config import get_settings
from app.db import session_scope, utcnow
from app.models import (
    ApplicationStatus, FacilityType, Hospital, HospitalKind, HospitalStatus, OnboardingApplication,
    OnboardingDocument, Role, StaffUser,
)
from app.security import hash_password, password_problem
from app.validation import ContactNumber, Name, OptionalPhone, OptionalText

router = APIRouter(tags=["onboarding"])

#: Sign-ups per address per hour (a hospital signs up once).
SIGNUPS_PER_HOUR = 5
#: Addresses tracked; the least recently seen are forgotten first.
_TRACKED = 10_000
_signups: "OrderedDict[str, Deque[float]]" = OrderedDict()
_signups_lock = threading.Lock()


class HospitalSignup(BaseModel):
    """The first step of the application: the facility's name and the contact
    person's account. The rest (kind, city, location, ...) follows in the
    wizard; earlier clients send ``kind`` and ``city`` here, which still works."""

    hospital_name: Name = Field(max_length=160)
    hospital_name_am: OptionalText = Field(default=None, max_length=160)
    #: Ownership: public or private.
    kind: Optional[str] = None
    #: Hospital or clinic.
    facility_type: Optional[str] = None
    city: Optional[Name] = Field(default=None, max_length=100)
    phone: ContactNumber = None
    admin_name: Name = Field(max_length=120)
    #: The contact person's role or title, e.g. Medical Director.
    admin_title: OptionalText = Field(default=None, max_length=80)
    #: The contact person's mobile (Endod texts the demo confirmation to it).
    admin_phone: OptionalPhone = None
    admin_email: EmailStr
    password: str = Field(min_length=1, max_length=200)


def _rate_limited(key: str) -> bool:
    now = time.monotonic()
    with _signups_lock:
        hits = _signups.pop(key, None) or deque()
        _signups[key] = hits  # most recently seen last
        while hits and hits[0] < now - 3600:
            hits.popleft()
        if len(hits) >= SIGNUPS_PER_HOUR:
            return True
        hits.append(now)
        while len(_signups) > _TRACKED:
            _signups.popitem(last=False)
        return False


def client_address(request: Request) -> str:
    """The caller's address. X-Forwarded-For is used only through the configured
    number of trusted proxies (counted from the right), so a client cannot
    choose its own address by sending the header."""
    hops = get_settings().TRUSTED_PROXY_HOPS
    if hops > 0:
        entries = [e.strip() for e in request.headers.get("x-forwarded-for", "").split(",") if e.strip()]
        if len(entries) >= hops:
            return entries[-hops]
    return request.client.host if request.client else "unknown"


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
    if _rate_limited(client_address(request)):
        raise HTTPException(status_code=429, detail="Too many sign-ups from here. Try again later.")
    if body.kind is not None and body.kind not in HospitalKind.ALL:
        raise HTTPException(status_code=400, detail=f"kind must be one of {list(HospitalKind.ALL)}.")
    if body.facility_type is not None and body.facility_type not in FacilityType.ALL:
        raise HTTPException(status_code=400, detail=f"facility_type must be one of {list(FacilityType.ALL)}.")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    email = body.admin_email.lower()
    try:
        with session_scope() as session:
            hospital = Hospital(
                code=_code_for(session, body.hospital_name), name=body.hospital_name,
                name_am=body.hospital_name_am, kind=body.kind or HospitalKind.PRIVATE,
                facility_type=body.facility_type or FacilityType.HOSPITAL, city=body.city, phone=body.phone,
                status=HospitalStatus.PENDING, timezone=settings.DEFAULT_TIMEZONE,
            )
            session.add(hospital)
            session.flush()
            admin = StaffUser(
                hospital_id=hospital.id, email=email, full_name=body.admin_name, role=Role.ADMIN,
                phone=body.admin_phone, password_hash=hash_password(body.password), must_change_password=False,
            )
            session.add(admin)
            session.add(OnboardingApplication(hospital_id=hospital.id, status=ApplicationStatus.DRAFT,
                                              contact_title=body.admin_title))
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
        hospitals = list(session.scalars(query))
        # Who signed up, so Endod can check the hospital before approving it.
        admins: Dict[str, Dict[str, str]] = {}
        for user in session.scalars(select(StaffUser).where(
                StaffUser.hospital_id.in_([h.id for h in hospitals] or [""]), StaffUser.role == Role.ADMIN)
                .order_by(StaffUser.created_at)):
            admins.setdefault(user.hospital_id, {"name": user.full_name, "email": user.email,
                                                 "phone": user.phone or ""})
        return [{**hospital_payload(h), "created_at": h.created_at.isoformat(), "contact": admins.get(h.id)}
                for h in hospitals]


NOT_SUBMITTED = ("The hospital's application is not submitted yet (status: {status}); "
                 "only a submitted application can be approved.")


def set_status(hospital_id: str, new_status: str, force: bool = False) -> Dict[str, Any]:
    """Approve or suspend a hospital, and update the patient app's listing.

    Approving needs a submitted application (or one approved before: a
    suspended hospital coming back). ``force`` (the CLI's ``--force``) skips
    that check on purpose, and the audit log says so.
    """
    with session_scope() as session:
        hospital = session.scalar(select(Hospital).where(Hospital.id == hospital_id).with_for_update())
        if hospital is None:
            raise HTTPException(status_code=404, detail="Hospital not found.")
        application = onboarding.application_for(session, hospital, lock=True)
        forced = False
        if new_status == HospitalStatus.APPROVED and application.status not in (
                ApplicationStatus.SUBMITTED, ApplicationStatus.APPROVED):
            if not force:
                raise HTTPException(status_code=409, detail=NOT_SUBMITTED.format(status=application.status))
            forced = True
        hospital.status = new_status
        if new_status == HospitalStatus.APPROVED and hospital.approved_at is None:
            hospital.approved_at = utcnow()
        if new_status == HospitalStatus.APPROVED:
            application.status = ApplicationStatus.APPROVED
        elif application.status != ApplicationStatus.APPROVED:
            # A suspended applicant gives its demo slot back.
            onboarding.release_demo(session, hospital.id)
        audit(session, hospital.id, None, f"hospital_{new_status}", "hospital", hospital.id,
              {"forced": True, "application_status": "not submitted"} if forced else None)
        listing.announce(session, hospital)
        session.flush()
        return hospital_payload(hospital)


@router.post("/platform/hospitals/{hospital_id}/approve", dependencies=[Depends(platform_admin)])
def approve(hospital_id: str) -> Dict[str, Any]:
    return set_status(hospital_id, HospitalStatus.APPROVED)


@router.post("/platform/hospitals/{hospital_id}/suspend", dependencies=[Depends(platform_admin)])
def suspend(hospital_id: str) -> Dict[str, Any]:
    return set_status(hospital_id, HospitalStatus.SUSPENDED)


@router.delete("/platform/hospitals/{hospital_id}", dependencies=[Depends(platform_admin)])
def remove_pending(hospital_id: str) -> Dict[str, Any]:
    """Delete a sign-up Endod will not accept (only while pending), freeing its emails."""
    with session_scope() as session:
        hospital = session.scalar(select(Hospital).where(Hospital.id == hospital_id).with_for_update())
        if hospital is None:
            raise HTTPException(status_code=404, detail="Hospital not found.")
        if hospital.status != HospitalStatus.PENDING:
            raise HTTPException(status_code=409, detail="Only a pending sign-up can be deleted; suspend instead.")
        document_ids = list(session.scalars(select(OnboardingDocument.id)
                                            .where(OnboardingDocument.hospital_id == hospital_id)))
        session.delete(hospital)
    # Its documents' files go too (the rows went with the hospital).
    for document_id in document_ids:
        files.delete(hospital_id, document_id)
    return {"deleted": hospital_id}
