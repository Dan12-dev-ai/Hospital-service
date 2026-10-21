"""Linking hospital patients to Endod accounts (docs/history-events.md, section 1).

Reception asks Endod to confirm who the patient is, by the health card's QR
(its signature) or by the Endod ID and the account's phone number
(``patient.link_requested``). The platform answers ``patient.linked`` or
``patient.link_refused``; only then is ``dedan_id`` stored on the patient
and their records published. Checking in an Endod booking links the patient
directly: the platform already identified them.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import eventbus, records
from app.db import utcnow
from app.eventbus import PermanentEventError
from app.models import LinkStatus, Patient, PatientLinkRequest
from app.validation import normalize_dedan_id

logger = logging.getLogger("hospital.linking")

CARD_HOSTS = {"endod-health.com", "www.endod-health.com"}
_CARD_PATH = re.compile(r"^/card/([A-Za-z0-9-]{6,12})/?$")
_SIGNATURE = re.compile(r"^[A-Za-z0-9_.~=-]{8,512}$")
_HEX_ID = re.compile(r"^[0-9a-f]{32}$")


class LinkError(ValueError):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def parse_card_url(url: str) -> Tuple[str, str]:
    """(dedan_id, signature) from the health card's QR,
    ``https://endod-health.com/card/<DEDAN_ID>?s=<SIGNATURE>``."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError as exc:
        raise LinkError("This is not an Endod health card.", 400) from exc
    match = _CARD_PATH.match(parts.path or "")
    signature = (parse_qs(parts.query).get("s") or [""])[0]
    if parts.scheme != "https" or (parts.hostname or "").lower() not in CARD_HOSTS or not match \
            or not _SIGNATURE.match(signature):
        raise LinkError("This is not an Endod health card.", 400)
    try:
        return normalize_dedan_id(match.group(1)), signature
    except ValueError as exc:
        raise LinkError("This is not an Endod health card.", 400) from exc


def holder_of(session: Session, hospital_id: str, dedan_id: str) -> Optional[Patient]:
    return session.scalar(select(Patient).where(Patient.hospital_id == hospital_id, Patient.dedan_id == dedan_id))


def _close_pending(session: Session, patient_id: str, status: str, reason: str) -> None:
    for request in session.scalars(select(PatientLinkRequest).where(
            PatientLinkRequest.patient_id == patient_id, PatientLinkRequest.status == LinkStatus.PENDING)):
        request.status, request.reason, request.decided_at = status, reason, utcnow()


def request_link(session: Session, patient: Patient, dedan_id: str, staff_id: Optional[str], *,
                 card_signature: Optional[str] = None, phone: Optional[str] = None) -> PatientLinkRequest:
    """Ask Endod to confirm the patient's account (``patient`` is locked)."""
    if patient.dedan_id:
        raise LinkError(f"This patient is already linked to {patient.dedan_id}. Unlink first.")
    other = holder_of(session, patient.hospital_id, dedan_id)
    if other is not None:
        raise LinkError(f"{dedan_id} is already linked to {other.full_name} ({other.mrn}).")
    if not card_signature and not phone:
        raise LinkError("Scan the health card, or give the phone number on the Endod account.", 400)
    _close_pending(session, patient.id, LinkStatus.SUPERSEDED, "replaced")
    request = PatientLinkRequest(
        hospital_id=patient.hospital_id, patient_id=patient.id, dedan_id=dedan_id,
        method="card" if card_signature else "phone", requested_by=staff_id,
    )
    session.add(request)
    session.flush()
    # Only what Endod needs to check the account; nothing else about the patient.
    eventbus.emit(session, "patient.link_requested", {
        "request_id": request.id, "hospital_id": patient.hospital_id, "patient_id": patient.id,
        "dedan_id": dedan_id, "card_signature": card_signature,
        "phone": None if card_signature else phone,
    })
    return request


def link(session: Session, patient: Patient, dedan_id: str, today: date) -> None:
    """Store the confirmed Endod ID and send the patient's history (``patient`` is locked)."""
    if patient.dedan_id == dedan_id:
        return
    if patient.dedan_id:
        raise LinkError(f"This patient is already linked to {patient.dedan_id}.")
    other = holder_of(session, patient.hospital_id, dedan_id)
    if other is not None and other.id != patient.id:
        raise LinkError(f"{dedan_id} is already linked to {other.full_name} ({other.mrn}).")
    patient.dedan_id = dedan_id
    # The confirmed ID replaces whatever ID the patient had given.
    patient.claimed_dedan_id = None
    session.flush()
    _close_pending(session, patient.id, LinkStatus.SUPERSEDED, "linked")
    records.publish_history(session, patient, today)


def unlink(session: Session, patient: Patient) -> Optional[str]:
    """Forget the Endod ID (nothing more is sent), or withdraw a pending request.
    Returns the Endod ID that was linked, if any."""
    _close_pending(session, patient.id, LinkStatus.SUPERSEDED, "withdrawn")
    old, patient.dedan_id = patient.dedan_id, None
    return old


# --- events from the platform ---------------------------------------------------------

class _Reply(BaseModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    hospital_id: str = Field(min_length=1, max_length=32)
    patient_id: str = Field(min_length=1, max_length=32)
    dedan_id: str = Field(min_length=1, max_length=16)


class Linked(_Reply):
    name: Optional[str] = Field(default=None, max_length=160)
    phone: Optional[str] = Field(default=None, max_length=20)


class Refused(_Reply):
    reason: str = Field(min_length=1, max_length=40)


def _parse(model, payload: Dict[str, Any]):
    try:
        parsed = model.model_validate(payload)
        dedan = normalize_dedan_id(parsed.dedan_id)
    except (ValidationError, ValueError) as exc:
        raise PermanentEventError(str(exc).splitlines()[0]) from exc
    return parsed, dedan


def _request_for(session: Session, reply: _Reply, dedan_id: str) -> Optional[PatientLinkRequest]:
    request = session.scalar(select(PatientLinkRequest).where(PatientLinkRequest.id == reply.request_id)
                             .with_for_update())
    if request is None:
        # Requests are made here, so a missing one was deleted with its patient.
        logger.info("link_reply_for_unknown_request id=%s", reply.request_id)
        return None
    if (request.hospital_id, request.patient_id, request.dedan_id) != (reply.hospital_id, reply.patient_id, dedan_id):
        raise PermanentEventError("the reply does not match its request")
    return request


def on_linked(session: Session, payload: Dict[str, Any]) -> None:
    reply, dedan_id = _parse(Linked, payload)
    request = _request_for(session, reply, dedan_id)
    if request is None or request.status != LinkStatus.PENDING:
        return  # answered already, or replaced by a newer request
    patient = session.scalar(select(Patient).where(Patient.id == request.patient_id).with_for_update())
    request.decided_at, request.linked_name = utcnow(), reply.name
    try:
        link(session, patient, dedan_id, records.hospital_today(session, patient.hospital_id))
    except LinkError:
        # Linked to someone else meanwhile (another patient holds the ID, or
        # this one was linked through a booking): one Endod ID per patient.
        request.status, request.reason = LinkStatus.REFUSED, "already_linked"
        return
    request.status = LinkStatus.LINKED


def on_refused(session: Session, payload: Dict[str, Any]) -> None:
    reply, dedan_id = _parse(Refused, payload)
    request = _request_for(session, reply, dedan_id)
    if request is None or request.status != LinkStatus.PENDING:
        return
    request.status, request.reason, request.decided_at = LinkStatus.REFUSED, reply.reason, utcnow()


HANDLERS = {
    "patient.linked": on_linked,
    "patient.link_refused": on_refused,
}
