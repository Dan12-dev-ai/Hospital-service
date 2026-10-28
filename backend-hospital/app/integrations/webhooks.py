"""Events sent to a hospital system's webhook, signed like Stripe's.

* **Events:** booking.created, booking.confirmed, booking.cancelled,
  patient.linked, patient.unlinked (and endpoint.test from "Send test
  event"), to every connection of the hospital with the ``webhooks`` scope
  and a webhook URL. Bodies are thin: ids, statuses and times, never notes
  or clinical data (a connection with ``bookings.read`` fetches the rest).
* **Signature:** ``Endod-Signature: t=<unix time>,v1=<hex HMAC-SHA256 of
  "<t>.<body>" under the connection's webhook secret>``.
* **Delivery:** queued in ``webhook_deliveries`` in the transaction of the
  change (the body encrypted at rest), sent by the worker
  (:func:`deliver_due`) with retries and backoff for up to 24 hours. A 2xx
  answer is success; anything else (redirects included) is retried. Once
  delivered or given up, the body is deleted; status and attempts stay.
* **SSRF:** https only; the host is resolved at every send and every address
  it resolves to must be public (no private, loopback, link-local, shared or
  reserved ranges); the connection goes to the checked address (no second
  lookup to rebind), with TLS checked against the host name; redirects are
  never followed.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import ipaddress
import json
import logging
import secrets
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import ensure_aware, platform_session, utcnow
from app.integrations import scopes as S
from app.models import Booking, DeliveryStatus, IntegrationClient, Patient, WebhookDelivery

logger = logging.getLogger("hospital.webhooks")

EVENTS = ("booking.created", "booking.confirmed", "booking.cancelled", "patient.linked", "patient.unlinked")
TEST_EVENT = "endpoint.test"
SIGNATURE_HEADER = "Endod-Signature"
#: Seconds to wait before attempt n+1 (the last value repeats); given up 24 hours after the event.
BACKOFF = (60, 300, 900, 1800, 3600, 7200, 14400, 21600)
GIVE_UP_AFTER = timedelta(hours=24)
TIMEOUT_SECONDS = 10
#: A delivery being sent is not picked up again for this long.
LEASE = timedelta(minutes=2)
BATCH = 20


# --- signing ------------------------------------------------------------------------------------

def signature(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("ascii") + body, hashlib.sha256).hexdigest()


def signature_header(secret: str, timestamp: int, body: bytes) -> str:
    return f"t={timestamp},v1={signature(secret, timestamp, body)}"


def verify(secret: str, header: str, body: bytes, tolerance: int = 300, now: Optional[int] = None) -> bool:
    """What a receiver does (docs/integrations.md has it in Python, Node and C#)."""
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        timestamp = int(parts.get("t", ""))
    except ValueError:
        return False
    now = int(time.time()) if now is None else now
    if abs(now - timestamp) > tolerance:
        return False
    return hmac.compare_digest(parts.get("v1", ""), signature(secret, timestamp, body))


# --- queueing ---------------------------------------------------------------------------------

def _event(event_type: str, hospital_id: str, mode: str, data: Dict[str, Any]) -> Tuple[str, str]:
    event_id = f"evt_{secrets.token_hex(12)}"
    body = {"id": event_id, "type": event_type, "created": utcnow().isoformat(), "hospital_id": hospital_id,
            "mode": mode, "data": data}
    return event_id, json.dumps(body, separators=(",", ":"))


def _receivers(session: Session, hospital_id: str) -> List[IntegrationClient]:
    rows = session.scalars(select(IntegrationClient).where(
        IntegrationClient.hospital_id == hospital_id, IntegrationClient.revoked_at.is_(None),
        IntegrationClient.webhook_url.is_not(None)))
    return [c for c in rows if S.WEBHOOKS in S.parse(c.scopes)]


def _queue(session: Session, client: IntegrationClient, event_type: str, data: Dict[str, Any]) -> WebhookDelivery:
    event_id, body = _event(event_type, client.hospital_id, client.mode, data)
    delivery = WebhookDelivery(hospital_id=client.hospital_id, client_pk=client.id, event_id=event_id,
                               event_type=event_type, body=body, status=DeliveryStatus.PENDING, attempts=0,
                               next_attempt_at=utcnow())
    session.add(delivery)
    return delivery


def emit(session: Session, hospital_id: str, event_type: str, data: Dict[str, Any]) -> int:
    """Queue an event for every connection of the hospital that receives events
    (in the caller's transaction). Returns how many."""
    assert event_type in EVENTS, event_type
    receivers = _receivers(session, hospital_id)
    for client in receivers:
        _queue(session, client, event_type, data)
    return len(receivers)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return ensure_aware(value).isoformat() if value else None


def booking_event(session: Session, booking: Booking, event_type: str) -> int:
    session.flush()
    return emit(session, booking.hospital_id, event_type, {
        "booking_id": booking.id, "endod_appointment_id": booking.external_id, "status": booking.status,
        "visit_mode": booking.visit_mode, "service": booking.service,
        "scheduled_at": _iso(booking.scheduled_at), "duration_minutes": booking.duration_minutes,
        "patient": {"endod_id": booking.patient_dedan_id},
    })


def patient_event(session: Session, patient: Patient, event_type: str, endod_id: Optional[str]) -> int:
    return emit(session, patient.hospital_id, event_type,
                {"patient_id": patient.id, "mrn": patient.mrn, "endod_id": endod_id})


def send_test(session: Session, client: IntegrationClient) -> WebhookDelivery:
    return _queue(session, client, TEST_EVENT, {"message": "A test event from Endod: your endpoint works."})


# --- where events may go (SSRF) ------------------------------------------------------------------

class Blocked(ValueError):
    """The destination is not allowed (not https, or not a public address)."""


def public_address(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return public_address(ip.ipv4_mapped)
        if ip.teredo is not None or (ip.sixtofour is not None and not public_address(ip.sixtofour)):
            return False
    return bool(ip.is_global) and not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                                       or ip.is_reserved or ip.is_unspecified)


def resolve(host: str, port: int) -> List[str]:
    """Every address ``host`` resolves to, now; Blocked unless all are public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, ValueError):
        raise Blocked("the host name does not resolve") from None
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise Blocked("the host name does not resolve")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            raise Blocked("the host resolves to an unusable address") from None
        if not public_address(ip):
            raise Blocked("the host resolves to a private, local or reserved address")
    return addresses


def destination(url: str) -> Tuple[str, int, str, List[str]]:
    """(host, port, path with query, checked addresses). Raises Blocked."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise Blocked("only https addresses with a host are allowed")
    port = parts.port or 443
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return parts.hostname, port, path, resolve(parts.hostname, port)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connects to an address already checked, while TLS (SNI, certificate)
    and the Host header use the host name."""

    def __init__(self, host: str, address: str, port: int, timeout: float, context: ssl.SSLContext):
        super().__init__(host, port, timeout=timeout, context=context)
        self._address = address

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


@dataclass
class Sent:
    ok: bool
    status_code: Optional[int]
    error: Optional[str]


def post(url: str, headers: Dict[str, str], body: bytes) -> Sent:
    """POST ``body`` to ``url`` (SSRF-checked at this moment; no redirects)."""
    try:
        host, port, path, addresses = destination(url)
    except Blocked as exc:
        return Sent(False, None, f"blocked: {exc}")
    connection = _PinnedHTTPSConnection(host, addresses[0], port, TIMEOUT_SECONDS, ssl.create_default_context())
    try:
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        response.read(1024)  # never kept
        status = response.status
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        return Sent(False, None, f"{type(exc).__name__}: could not deliver")
    finally:
        connection.close()
    if 200 <= status < 300:
        return Sent(True, status, None)
    if 300 <= status < 400:
        return Sent(False, status, "redirects are not followed")
    return Sent(False, status, f"answered {status}")


# --- the worker ----------------------------------------------------------------------------------

@dataclass
class _Job:
    delivery_id: str
    url: str
    secret: str
    body: str
    event_id: str
    event_type: str


def _give_up(delivery: WebhookDelivery, reason: str) -> None:
    delivery.status, delivery.body, delivery.next_attempt_at = DeliveryStatus.FAILED, None, None
    delivery.last_error = reason[:200]


def _claim(now: datetime, limit: int) -> List[_Job]:
    from app.integrations.tokens import hospital_open

    jobs: List[_Job] = []
    with platform_session() as session:  # every hospital's, for the worker
        due = session.scalars(select(WebhookDelivery).where(
            WebhookDelivery.status == DeliveryStatus.PENDING, WebhookDelivery.next_attempt_at <= now)
            .order_by(WebhookDelivery.next_attempt_at).limit(limit).with_for_update(skip_locked=True)).all()
        for delivery in due:
            client = session.get(IntegrationClient, delivery.client_pk)
            if client is None or client.revoked_at is not None or not client.webhook_url \
                    or not client.webhook_secret:
                _give_up(delivery, "the connection was removed or has no webhook")
                continue
            if not hospital_open(session, delivery.hospital_id):
                _give_up(delivery, "the hospital is not approved or is suspended")
                continue
            if delivery.event_type != TEST_EVENT and S.WEBHOOKS not in S.parse(client.scopes):
                _give_up(delivery, "the connection no longer receives events")
                continue
            delivery.attempts += 1
            delivery.last_attempt_at = now
            delivery.next_attempt_at = now + LEASE
            jobs.append(_Job(delivery.id, client.webhook_url, client.webhook_secret, delivery.body or "",
                             delivery.event_id, delivery.event_type))
    return jobs


def _send(job: _Job) -> Sent:
    body = job.body.encode("utf-8")
    headers = {
        "Content-Type": "application/json", "User-Agent": "Endod-Webhooks/1",
        SIGNATURE_HEADER: signature_header(job.secret, int(time.time()), body),
        "Endod-Event-Id": job.event_id, "Endod-Event-Type": job.event_type,
    }
    return post(job.url, headers, body)


def _record(results: List[Tuple[_Job, Sent]], now: datetime) -> None:
    with platform_session() as session:
        for job, sent in results:
            delivery = session.get(WebhookDelivery, job.delivery_id)
            if delivery is None or delivery.status != DeliveryStatus.PENDING:
                continue
            delivery.last_status_code = sent.status_code
            if sent.ok:
                delivery.status, delivery.delivered_at, delivery.body = DeliveryStatus.DELIVERED, now, None
                delivery.next_attempt_at, delivery.last_error = None, None
                continue
            delivery.last_error = (sent.error or "failed")[:200]
            wait = timedelta(seconds=BACKOFF[min(delivery.attempts - 1, len(BACKOFF) - 1)])
            if now + wait > ensure_aware(delivery.created_at) + GIVE_UP_AFTER:
                _give_up(delivery, f"gave up after {delivery.attempts} attempts: {delivery.last_error}")
            else:
                delivery.next_attempt_at = now + wait


def deliver_due(limit: int = BATCH, now: Optional[datetime] = None) -> int:
    """Send the deliveries that are due (the worker calls this every round). Returns how many were tried."""
    given = now
    now = now or utcnow()
    jobs = _claim(now, limit)
    if not jobs:
        return 0
    results = []
    for job in jobs:
        sent = _send(job)
        logger.info("webhook_attempt delivery=%s event=%s ok=%s status=%s", job.delivery_id, job.event_type,
                    sent.ok, sent.status_code)
        results.append((job, sent))
    _record(results, given or utcnow())
    return len(jobs)
