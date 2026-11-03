"""Linking hospital patients to Endod accounts (docs/history-events.md, section 1).

Reception asks Endod to confirm who the patient is, by the health card's QR
(its signature) or by the Endod ID and the account's phone number
(``patient.link_requested``). The platform answers ``patient.linked`` or
``patient.link_refused``; only then is ``dedan_id`` stored on the patient
and their records published. Checking in an Endod booking links the patient
directly: the platform already identified them.

A patient without an Endod account (often without a smartphone) is enrolled
by SMS (section 8 of the contract): ``patient.sms_enrol_requested`` makes
Endod text a code to the patient's phone (``patient.sms_enrol_code_sent``);
reception types the code the patient reads out (``patient.sms_enrol_verify``,
with the patient's name and language); Endod creates or finds the account,
links it and texts the patient their card number and PIN
(``patient.sms_enrolled``), or refuses (``patient.sms_enrol_refused``). The
enrolled patient is then linked exactly as on ``patient.linked``.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import eventbus, records
from app.integrations import webhooks
from app.db import utcnow
from app.eventbus import PermanentEventError
from app.models import LinkStatus, Patient, PatientLinkRequest, SmsEnrolment, SmsEnrolmentStatus
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
    _close_enrolments(session, patient.id, "replaced")
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


def link(session: Session, patient: Patient, dedan_id: str, today: date, request_id: Optional[str] = None) -> None:
    """Store the confirmed Endod ID and send the patient's history (``patient`` is locked).
    ``request_id``: the link request Endod answered (None when a booking's check-in linked them)."""
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
    _close_enrolments(session, patient.id, "linked")
    records.publish_history(session, patient, today)
    webhooks.patient_event(session, patient, "patient.linked", dedan_id, request_id=request_id)


def unlink(session: Session, patient: Patient) -> Optional[str]:
    """Forget the Endod ID (nothing more is sent), or withdraw a pending request.
    Returns the Endod ID that was linked, if any."""
    _close_pending(session, patient.id, LinkStatus.SUPERSEDED, "withdrawn")
    _close_enrolments(session, patient.id, "withdrawn")
    old, patient.dedan_id = patient.dedan_id, None
    if old:
        webhooks.patient_event(session, patient, "patient.unlinked", old)
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
        link(session, patient, dedan_id, records.hospital_today(session, patient.hospital_id), request.id)
    except LinkError:
        # Linked to someone else meanwhile (another patient holds the ID, or
        # this one was linked through a booking): one Endod ID per patient.
        request.status, request.reason = LinkStatus.REFUSED, "already_linked"
        _refused_event(session, request)
        return
    request.status = LinkStatus.LINKED


def on_refused(session: Session, payload: Dict[str, Any]) -> None:
    reply, dedan_id = _parse(Refused, payload)
    request = _request_for(session, reply, dedan_id)
    if request is None or request.status != LinkStatus.PENDING:
        return
    request.status, request.reason, request.decided_at = LinkStatus.REFUSED, reply.reason, utcnow()
    _refused_event(session, request)


def _refused_event(session: Session, request: PatientLinkRequest) -> None:
    """Tell the hospital's systems (webhook ``patient.link_refused``)."""
    patient = session.get(Patient, request.patient_id)
    if patient is not None:
        webhooks.patient_event(session, patient, "patient.link_refused", request.dedan_id,
                               request_id=request.id, reason=request.reason)


# --- enrolment by SMS (section 8) -----------------------------------------------------

#: Refusals after which the code may be typed again.
_RETRYABLE = {"wrong_code"}
#: Endod's refusals, as stored (anything else is kept as "refused").
ENROL_REASONS = {"invalid_phone", "rate_limited", "sms_unavailable", "wrong_code", "too_many_attempts", "expired",
                 "superseded", "no_code", "not_allowed"}


def _close_enrolments(session: Session, patient_id: str, reason: str) -> None:
    for row in session.scalars(select(SmsEnrolment).where(
            SmsEnrolment.patient_id == patient_id, SmsEnrolment.status.in_(SmsEnrolmentStatus.OPEN))):
        row.status, row.reason, row.decided_at = SmsEnrolmentStatus.SUPERSEDED, reason, utcnow()


def latest_enrolment(session: Session, patient_id: str) -> Optional[SmsEnrolment]:
    return session.scalar(select(SmsEnrolment).where(SmsEnrolment.patient_id == patient_id)
                          .order_by(SmsEnrolment.created_at.desc(), SmsEnrolment.id.desc()).limit(1))


def request_sms_enrolment(session: Session, patient: Patient, phone: Optional[str]) -> SmsEnrolment:
    """Ask Endod to text the patient a code (``patient`` is locked). ``phone``
    (normalised): where, else the patient's own number."""
    if patient.dedan_id:
        raise LinkError(f"This patient is already linked to {patient.dedan_id}.")
    phone = phone or patient.phone
    if not phone:
        raise LinkError("The patient has no phone number: give one.", 400)
    _close_pending(session, patient.id, LinkStatus.SUPERSEDED, "replaced")
    _close_enrolments(session, patient.id, "replaced")
    row = SmsEnrolment(hospital_id=patient.hospital_id, patient_id=patient.id, phone=phone,
                       status=SmsEnrolmentStatus.SENDING)
    session.add(row)
    session.flush()
    # The phone only: nothing else about the patient before the code is checked.
    eventbus.emit(session, "patient.sms_enrol_requested", {
        "request_id": row.id, "hospital_id": patient.hospital_id, "patient_id": patient.id, "phone": phone})
    return row


def verify_sms_enrolment(session: Session, patient: Patient, code: str, language: str) -> SmsEnrolment:
    """Send the code the patient read out to Endod to check (``patient`` is locked)."""
    if patient.dedan_id:
        raise LinkError(f"This patient is already linked to {patient.dedan_id}.")
    row = latest_enrolment(session, patient.id)
    if row is None or row.status not in (SmsEnrolmentStatus.SENDING, SmsEnrolmentStatus.CODE_SENT):
        raise LinkError("No code is waiting for this patient: send one first (POST /patients/{mrn}/sms-enrol).")
    row.status, row.reason = SmsEnrolmentStatus.VERIFYING, None
    session.flush()
    # Now the patient's name and language too: Endod may create their account.
    eventbus.emit(session, "patient.sms_enrol_verify", {
        "request_id": row.id, "hospital_id": patient.hospital_id, "patient_id": patient.id, "code": code,
        "name": patient.full_name, "language": language})
    return row


class _EnrolReply(BaseModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    hospital_id: str = Field(min_length=1, max_length=32)
    patient_id: str = Field(min_length=1, max_length=32)


class _CodeSent(_EnrolReply):
    expires_at: Optional[datetime] = None


class _EnrolRefused(_EnrolReply):
    reason: str = Field(min_length=1, max_length=40)
    attempts_left: Optional[int] = Field(default=None, ge=0)


class _Enrolled(_EnrolReply):
    dedan_id: str = Field(min_length=1, max_length=16)
    name: Optional[str] = Field(default=None, max_length=160)
    phone: Optional[str] = Field(default=None, max_length=20)
    created: bool = False


def _parse_reply(model, payload: Dict[str, Any]):
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise PermanentEventError(str(exc).splitlines()[0]) from exc


def _enrolment_for(session: Session, reply: _EnrolReply) -> Optional[SmsEnrolment]:
    row = session.scalar(select(SmsEnrolment).where(SmsEnrolment.id == reply.request_id).with_for_update())
    if row is None:
        # Requests are made here, so a missing one was deleted with its patient.
        logger.info("sms_enrol_reply_for_unknown_request id=%s", reply.request_id)
        return None
    if (row.hospital_id, row.patient_id) != (reply.hospital_id, reply.patient_id):
        raise PermanentEventError("the reply does not match its request")
    return row


def _enrolment_event(session: Session, row: SmsEnrolment) -> None:
    """Tell the hospital's systems (webhook ``patient.sms_enrolment``)."""
    patient = session.get(Patient, row.patient_id)
    if patient is not None:
        webhooks.patient_event(session, patient, "patient.sms_enrolment", row.dedan_id, request_id=row.id,
                               status=row.status, reason=row.reason, attempts_left=row.attempts_left)


def on_sms_code_sent(session: Session, payload: Dict[str, Any]) -> None:
    reply = _parse_reply(_CodeSent, payload)
    row = _enrolment_for(session, reply)
    if row is None or row.status != SmsEnrolmentStatus.SENDING:
        return  # answered already, replaced, or the code was typed meanwhile
    row.status, row.code_expires_at = SmsEnrolmentStatus.CODE_SENT, reply.expires_at
    _enrolment_event(session, row)


def on_sms_refused(session: Session, payload: Dict[str, Any]) -> None:
    reply = _parse_reply(_EnrolRefused, payload)
    row = _enrolment_for(session, reply)
    if row is None or row.status not in SmsEnrolmentStatus.OPEN:
        return
    reason = reply.reason if reply.reason in ENROL_REASONS else "refused"
    row.reason, row.attempts_left = reason, reply.attempts_left
    if reason in _RETRYABLE and (reply.attempts_left or 0) > 0:
        row.status = SmsEnrolmentStatus.CODE_SENT  # the code may be typed again
    else:
        row.status, row.decided_at = SmsEnrolmentStatus.FAILED, utcnow()
    _enrolment_event(session, row)


def on_sms_enrolled(session: Session, payload: Dict[str, Any]) -> None:
    reply = _parse_reply(_Enrolled, payload)
    try:
        dedan_id = normalize_dedan_id(reply.dedan_id)
    except ValueError as exc:
        raise PermanentEventError("not an Endod ID") from exc
    row = _enrolment_for(session, reply)
    if row is None or row.status not in SmsEnrolmentStatus.OPEN:
        return
    patient = session.scalar(select(Patient).where(Patient.id == row.patient_id).with_for_update())
    row.decided_at, row.dedan_id, row.created_account = utcnow(), dedan_id, reply.created
    try:
        link(session, patient, dedan_id, records.hospital_today(session, patient.hospital_id), row.id)
    except LinkError:
        # Another patient of this hospital holds the Endod ID (the same person
        # registered twice), or this one was linked another way meanwhile.
        row.status, row.reason = SmsEnrolmentStatus.FAILED, "already_linked"
        _enrolment_event(session, row)
        return
    # link() closed the open enrolments (as superseded): this one is the link.
    row.status, row.reason, row.attempts_left = SmsEnrolmentStatus.ENROLLED, None, None
    _enrolment_event(session, row)


HANDLERS = {
    "patient.linked": on_linked,
    "patient.link_refused": on_refused,
    "patient.sms_enrol_code_sent": on_sms_code_sent,
    "patient.sms_enrol_refused": on_sms_refused,
    "patient.sms_enrolled": on_sms_enrolled,
}
