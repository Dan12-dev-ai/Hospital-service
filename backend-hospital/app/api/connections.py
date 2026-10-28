"""Connections of a hospital's own systems to the integration API, managed
in the portal ("Connect your system"): admins of hospitals approved by Endod
only.

Connecting a system, changing its credentials (rotating a secret, public
keys), where it may call from, where its events go, and disconnecting it,
each needs the admin's password again (app.auth.confirm_identity) and is
audited (ids, names and scopes; never a secret). Secrets are shown once,
in the answer that creates them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.auth import AuthError, Staff, audit, confirm_identity, require_roles
from app.db import ensure_aware, session_scope, utcnow
from app.integrations import clients, fhir, jose, scopes as S, tokens, webhooks
from app.models import (
    DeliveryStatus, Hospital, HospitalStatus, IntegrationAuth, IntegrationClient, IntegrationMode, IntegrationRequest,
    Role, StaffUser, WebhookDelivery,
)
from app.validation import Name

router = APIRouter(prefix="/connections", tags=["connections"])

NOT_APPROVED = "Only hospitals approved by Endod can connect their systems."
MAX_CONNECTIONS = 20
RECENT = 50


def approved_admin(staff: Staff = Depends(require_roles(Role.ADMIN))) -> Staff:
    """An admin of a hospital that passed onboarding and is not suspended."""
    if staff.hospital_status != HospitalStatus.APPROVED or staff.locked:
        raise HTTPException(status_code=403, detail=NOT_APPROVED)
    return staff


class Confirmed(BaseModel):
    #: The admin's password, typed again.
    password: str = Field(default="", max_length=200)


class NewConnection(Confirmed):
    name: Name = Field(max_length=80)
    scopes: List[str] = Field(min_length=1, max_length=len(S.ALL))
    mode: str = IntegrationMode.LIVE
    webhook_url: Optional[str] = Field(default=None, max_length=500)


class IpRestriction(Confirmed):
    #: Addresses or ranges; empty: any address.
    allowed_ips: List[str] = Field(default_factory=list, max_length=clients.MAX_CIDRS)


class PublicKeys(Confirmed):
    #: A JWKS, as JSON text or an object.
    jwks: Union[str, Dict[str, Any]]


class Webhook(Confirmed):
    #: null removes the webhook.
    url: Optional[str] = Field(default=None, max_length=500)


def _iso(value) -> Optional[str]:
    return ensure_aware(value).isoformat() if value else None


def _payload(session, c: IntegrationClient) -> Dict[str, Any]:
    granted = S.ordered(S.parse(c.scopes))
    author = session.get(StaffUser, c.created_by) if c.created_by else None
    return {
        "id": c.id, "name": c.name, "client_id": c.client_id, "mode": c.mode, "scopes": granted,
        "abilities": [S.SCOPES[s][0] for s in granted], "auth_method": c.auth_method,
        "allowed_ips": clients.stored_cidrs(c.allowed_cidrs), "webhook_url": c.webhook_url,
        "public_keys": len(jose.parse_jwks(c.jwks)) if c.jwks and c.auth_method == IntegrationAuth.PRIVATE_KEY_JWT
        else 0,
        "created_at": _iso(c.created_at), "created_by": author.full_name if author else None,
        "last_used_at": _iso(c.last_used_at), "revoked_at": _iso(c.revoked_at),
    }


def _about(session, hospital_id: str) -> Dict[str, Any]:
    base = tokens.public_url()
    return {"api_url": base, "token_url": tokens.token_url(), "docs_url": f"{base}/docs",
            "jwks_url": f"{base}/.well-known/jwks.json", "fhir_url": f"{base}/fhir",
            "mrn_system": fhir.mrn_system(session.get(Hospital, hospital_id)), "scopes": S.describe()}


def _confirm(staff: Staff, password: str) -> None:
    try:
        confirm_identity(staff, password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _client(session, staff: Staff, connection_id: str, lock: bool = True) -> IntegrationClient:
    query = select(IntegrationClient).where(IntegrationClient.id == connection_id,
                                            IntegrationClient.hospital_id == staff.hospital_id)
    client = session.scalar(query.with_for_update() if lock else query)
    if client is None:
        raise HTTPException(status_code=404, detail="Connection not found.")
    return client


def _live(client: IntegrationClient) -> None:
    if client.revoked_at is not None:
        raise HTTPException(status_code=409, detail="This system was disconnected.")


def _webhook_url(url: Optional[str]) -> str:
    try:
        return clients.check_webhook_url(url or "")
    except clients.WebhookUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_connections(staff: Staff = Depends(approved_admin)) -> Dict[str, Any]:
    with session_scope(staff.hospital_id) as session:
        rows = session.scalars(select(IntegrationClient).where(
            IntegrationClient.hospital_id == staff.hospital_id, IntegrationClient.revoked_at.is_(None))
            .order_by(IntegrationClient.created_at.desc()))
        return {"items": [_payload(session, c) for c in rows], **_about(session, staff.hospital_id)}


@router.post("", status_code=status.HTTP_201_CREATED)
def connect(body: NewConnection, staff: Staff = Depends(approved_admin)) -> Dict[str, Any]:
    """A new connection. The answer holds the client secret (and the webhook
    secret, if any): shown this once, never again."""
    unknown = S.unknown(body.scopes)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown abilities: {', '.join(unknown)[:200]}.")
    if body.mode not in IntegrationMode.ALL:
        raise HTTPException(status_code=400, detail="Choose Live or Test.")
    granted = S.ordered(body.scopes)
    webhook_url = None
    if S.WEBHOOKS in granted:
        webhook_url = _webhook_url(body.webhook_url)
    elif body.webhook_url:
        raise HTTPException(status_code=400, detail="An address for notifications needs \"Get notified of bookings\".")
    _confirm(staff, body.password)
    secret = clients.new_secret()
    webhook_secret = clients.new_webhook_secret() if webhook_url else None
    with session_scope(staff.hospital_id) as session:
        active = session.scalar(select(func.count()).where(
            IntegrationClient.hospital_id == staff.hospital_id, IntegrationClient.revoked_at.is_(None))) or 0
        if active >= MAX_CONNECTIONS:
            raise HTTPException(status_code=409, detail=f"At most {MAX_CONNECTIONS} systems can be connected; "
                                                        "disconnect one first.")
        client = IntegrationClient(
            hospital_id=staff.hospital_id, client_id=clients.new_client_id(body.mode), name=body.name,
            scopes=" ".join(granted), mode=body.mode, auth_method=IntegrationAuth.SECRET,
            secret_hash=clients.hash_secret(secret), webhook_url=webhook_url, webhook_secret=webhook_secret,
            created_by=staff.id)
        session.add(client)
        session.flush()
        audit(session, staff.hospital_id, staff.id, "integration_connected", "integration", client.id,
              {"client_id": client.client_id, "name": client.name, "scopes": granted, "mode": client.mode,
               "webhook": bool(webhook_url)})
        session.flush()
        return {"connection": _payload(session, client), "client_secret": secret, "webhook_secret": webhook_secret,
                **_about(session, staff.hospital_id)}


@router.get("/{connection_id}")
def read_connection(connection_id: str, staff: Staff = Depends(approved_admin)) -> Dict[str, Any]:
    with session_scope(staff.hospital_id) as session:
        client = _client(session, staff, connection_id, lock=False)
        return {"connection": _payload(session, client), **_about(session, staff.hospital_id)}


@router.post("/{connection_id}/disconnect")
def disconnect(connection_id: str, body: Confirmed, staff: Staff = Depends(approved_admin)) -> Dict[str, Any]:
    """Stops the system at once: no new tokens, and its current token is refused on the next call."""
    _confirm(staff, body.password)
    with session_scope(staff.hospital_id) as session:
        client = _client(session, staff, connection_id)
        _live(client)
        client.revoked_at = utcnow()
        client.secret_hash = None
        # Events waiting for it are dropped (bodies too).
        session.execute(update(WebhookDelivery).where(
            WebhookDelivery.client_pk == client.id, WebhookDelivery.status == DeliveryStatus.PENDING)
            .values(status=DeliveryStatus.FAILED, body=None, next_attempt_at=None,
                    last_error="the connection was removed"))
        audit(session, staff.hospital_id, staff.id, "integration_disconnected", "integration", client.id,
              {"client_id": client.client_id, "name": client.name})
        session.flush()
        return {"connection": _payload(session, client)}


@router.post("/{connection_id}/rotate-secret")
def rotate_secret(connection_id: str, body: Confirmed, staff: Staff = Depends(approved_admin)) -> Dict[str, Any]:
    """A new client secret (shown once); the old one, and tokens issued with it,
    stop working at once. On a connection using public keys, this switches it
    back to a secret."""
    _confirm(staff, body.password)
    secret = clients.new_secret()
    with session_scope(staff.hospital_id) as session:
        client = _client(session, staff, connection_id)
        _live(client)
        previous = client.auth_method
        client.auth_method, client.secret_hash, client.jwks = IntegrationAuth.SECRET, clients.hash_secret(secret), None
        client.credentials_changed_at = utcnow()
        audit(session, staff.hospital_id, staff.id, "integration_secret_rotated", "integration", client.id,
              {"client_id": client.client_id, "previous_method": previous})
        session.flush()
        return {"connection": _payload(session, client), "client_secret": secret}


@router.post("/{connection_id}/ip-restriction")
def ip_restriction(connection_id: str, body: IpRestriction, staff: Staff = Depends(approved_admin)) -> Dict[str, Any]:
    try:
        cidrs = clients.parse_cidrs(body.allowed_ips)
    except clients.CidrError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _confirm(staff, body.password)
    with session_scope(staff.hospital_id) as session:
        client = _client(session, staff, connection_id)
        _live(client)
        client.allowed_cidrs = ",".join(cidrs) or None
        audit(session, staff.hospital_id, staff.id, "integration_ips_set", "integration", client.id,
              {"client_id": client.client_id, "allowed_ips": cidrs})
        session.flush()
        return {"connection": _payload(session, client)}


@router.post("/{connection_id}/public-key")
def public_key(connection_id: str, body: PublicKeys, staff: Staff = Depends(approved_admin)) -> Dict[str, Any]:
    """Switch to public-key authentication (private_key_jwt), or replace the
    keys. The client secret stops working."""
    try:
        keys = jose.parse_jwks(body.jwks)
    except jose.JoseError as exc:
        raise HTTPException(status_code=400, detail=f"The public keys are not usable: {exc}.") from exc
    _confirm(staff, body.password)
    with session_scope(staff.hospital_id) as session:
        client = _client(session, staff, connection_id)
        _live(client)
        client.auth_method, client.jwks, client.secret_hash = IntegrationAuth.PRIVATE_KEY_JWT, jose.jwks_json(keys), None
        client.credentials_changed_at = utcnow()
        audit(session, staff.hospital_id, staff.id, "integration_public_keys_set", "integration", client.id,
              {"client_id": client.client_id, "keys": [jose.thumbprint(k.jwk) for k in keys]})
        session.flush()
        return {"connection": _payload(session, client)}


@router.post("/{connection_id}/webhook")
def set_webhook(connection_id: str, body: Webhook, staff: Staff = Depends(approved_admin)) -> Dict[str, Any]:
    """Set (or remove, with null) where events go. A new webhook gets a signing
    secret, shown once."""
    url = _webhook_url(body.url) if body.url else None
    _confirm(staff, body.password)
    with session_scope(staff.hospital_id) as session:
        client = _client(session, staff, connection_id)
        _live(client)
        granted = S.parse(client.scopes)
        secret = None
        if url:
            if not client.webhook_secret:
                secret = clients.new_webhook_secret()
                client.webhook_secret = secret
            granted = S.ordered(granted + [S.WEBHOOKS])
        else:
            client.webhook_secret = None
            granted = [s for s in granted if s != S.WEBHOOKS]
        if not granted:
            raise HTTPException(status_code=400, detail="A connection must be able to do something.")
        client.webhook_url, client.scopes = url, " ".join(granted)
        audit(session, staff.hospital_id, staff.id, "integration_webhook_set" if url else "integration_webhook_removed",
              "integration", client.id, {"client_id": client.client_id, "url": url})
        session.flush()
        return {"connection": _payload(session, client), "webhook_secret": secret}


@router.post("/{connection_id}/webhook/rotate-secret")
def rotate_webhook_secret(connection_id: str, body: Confirmed, staff: Staff = Depends(approved_admin)) \
        -> Dict[str, Any]:
    _confirm(staff, body.password)
    secret = clients.new_webhook_secret()
    with session_scope(staff.hospital_id) as session:
        client = _client(session, staff, connection_id)
        _live(client)
        if not client.webhook_url:
            raise HTTPException(status_code=409, detail="This connection has no address for notifications.")
        client.webhook_secret = secret
        audit(session, staff.hospital_id, staff.id, "integration_webhook_secret_rotated", "integration", client.id,
              {"client_id": client.client_id})
        session.flush()
        return {"connection": _payload(session, client), "webhook_secret": secret}


@router.post("/{connection_id}/webhook/test", status_code=status.HTTP_202_ACCEPTED)
def send_test_event(connection_id: str, staff: Staff = Depends(approved_admin)) -> Dict[str, Any]:
    with session_scope(staff.hospital_id) as session:
        client = _client(session, staff, connection_id)
        _live(client)
        if not client.webhook_url:
            raise HTTPException(status_code=409, detail="This connection has no address for notifications.")
        delivery = webhooks.send_test(session, client)
        session.flush()
        audit(session, staff.hospital_id, staff.id, "integration_webhook_tested", "integration", client.id,
              {"client_id": client.client_id, "event_id": delivery.event_id})
        return {"delivery_id": delivery.id, "event_id": delivery.event_id}


@router.get("/{connection_id}/requests")
def recent_requests(connection_id: str, staff: Staff = Depends(approved_admin)) -> Dict[str, Any]:
    with session_scope(staff.hospital_id) as session:
        client = _client(session, staff, connection_id, lock=False)
        rows = session.scalars(select(IntegrationRequest).where(IntegrationRequest.client_pk == client.id)
                               .order_by(IntegrationRequest.at.desc()).limit(RECENT))
        return {"items": [{"at": _iso(r.at), "method": r.method, "path": r.path, "status": r.status,
                           "duration_ms": r.duration_ms, "ip": r.ip} for r in rows]}


@router.get("/{connection_id}/deliveries")
def recent_deliveries(connection_id: str, staff: Staff = Depends(approved_admin)) -> Dict[str, Any]:
    with session_scope(staff.hospital_id) as session:
        client = _client(session, staff, connection_id, lock=False)
        rows = session.scalars(select(WebhookDelivery).where(WebhookDelivery.client_pk == client.id)
                               .order_by(WebhookDelivery.created_at.desc()).limit(RECENT))
        return {"items": [{"id": d.id, "event_id": d.event_id, "event_type": d.event_type, "status": d.status,
                           "attempts": d.attempts, "last_status_code": d.last_status_code,
                           "last_error": d.last_error, "created_at": _iso(d.created_at),
                           "last_attempt_at": _iso(d.last_attempt_at), "next_attempt_at": _iso(d.next_attempt_at),
                           "delivered_at": _iso(d.delivered_at)} for d in rows]}
