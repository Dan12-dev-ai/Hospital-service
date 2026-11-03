"""The developer dashboard's API playground: its own Test connection.

The playground (the dashboard's "try it") calls the integration API from the
dashboard's server (its BFF), never from the browser. It does so with a Test
connection the dashboard manages for the hospital:

* one per hospital, created on first use, marked ``playground``: never
  listed, counted, shown or changed through ``/connections`` (app/api/connections.py);
* Test mode only (``endod_test_...``): everything is checked, nothing is
  stored, no real patient is ever looked up (docs/integrations.md, Test mode);
* every scope but webhooks (it receives no events);
* its secret is never kept readable: each call here makes a new one (and the
  old one, and the tokens issued with it, stop working), answered to the
  BFF, which exchanges it for an access token at once and keeps only that
  token, in its memory, never sending either to the browser.

Administrators and developers of approved hospitals only; a few calls a
minute per hospital (the BFF reuses its access token for its 5 minutes).
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.connections import approved_admin
from app.auth import Staff, audit
from app.db import session_scope, utcnow
from app.integrations import clients, scopes as S, tokens
from app.integrations.ratelimit import Limiter
from app.models import Hospital, IntegrationAuth, IntegrationClient, IntegrationMode

router = APIRouter(prefix="/playground", tags=["playground"])

NAME = "Dashboard playground"
#: Every scope but webhooks: the playground receives no events.
SCOPES = tuple(s for s in S.ALL if s != S.WEBHOOKS)
#: New credentials per hospital (the BFF asks once per access token, every ~5 minutes).
CREDENTIALS_PER_HOSPITAL = Limiter(10, 60)


def playground_client(session, hospital_id: str) -> IntegrationClient:
    """The hospital's playground connection (created if missing), locked for this transaction."""
    # The hospital row is locked first, so two first uses cannot both create one.
    session.scalar(select(Hospital.id).where(Hospital.id == hospital_id).with_for_update())
    client = session.scalar(select(IntegrationClient).where(
        IntegrationClient.hospital_id == hospital_id, IntegrationClient.playground.is_(True),
        IntegrationClient.revoked_at.is_(None)).with_for_update())
    if client is None:
        client = IntegrationClient(
            hospital_id=hospital_id, client_id=clients.new_client_id(IntegrationMode.TEST), name=NAME,
            scopes=" ".join(SCOPES), mode=IntegrationMode.TEST, auth_method=IntegrationAuth.SECRET,
            playground=True)
        session.add(client)
        session.flush()
    # Kept as it must be, whatever happened to the row: Test, a secret, no address limit, no webhook.
    client.mode, client.auth_method, client.scopes = IntegrationMode.TEST, IntegrationAuth.SECRET, " ".join(SCOPES)
    client.allowed_cidrs = client.webhook_url = client.webhook_secret = client.jwks = None
    return client


@router.post("/credentials")
def credentials(staff: Staff = Depends(approved_admin)) -> Dict[str, Any]:
    """New credentials of the hospital's playground connection (Test mode), for
    the dashboard's server only (the BFF never passes this answer on)."""
    wait = CREDENTIALS_PER_HOSPITAL.hit(staff.hospital_id)
    if wait is not None:
        raise HTTPException(status_code=429, detail="Too many playground requests; try again shortly.",
                            headers={"Retry-After": str(wait)})
    secret = clients.new_secret()
    with session_scope(staff.hospital_id) as session:
        client = playground_client(session, staff.hospital_id)
        client.secret_hash = clients.hash_secret(secret)
        client.credentials_changed_at = utcnow()
        audit(session, staff.hospital_id, staff.id, "integration_playground_credentials", "integration", client.id,
              {"client_id": client.client_id})
        return {"client_id": client.client_id, "client_secret": secret, "mode": client.mode,
                "scopes": list(SCOPES), "token_url": tokens.token_url(), "api_url": tokens.public_url()}
