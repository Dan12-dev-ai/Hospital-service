"""The developer dashboard's own reads: the integration guide (its Docs
pages) and the hospital's price list (its Settings page). Administrators and
developers of hospitals approved by Endod, like the API keys.

The guide is app/integrations/guide.md, the single source of truth (the
integration API's OpenAPI description and docs/integrations.md are the same
text), served as Markdown; the dashboard splits it into pages.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.api.connections import approved_admin
from app.api.integrations import GUIDE
from app.auth import Staff
from app.db import session_scope
from app.integrations import pricing, tokens
from app.models import Hospital

router = APIRouter(tags=["developer"])


@router.get("/developer/guide")
def guide(staff: Staff = Depends(approved_admin)) -> Dict[str, Any]:
    base = tokens.public_url()
    return {"markdown": GUIDE.read_text(encoding="utf-8"), "api_url": base, "docs_url": f"{base}/docs",
            "openapi_url": f"{base}/openapi.json"}


@router.get("/prices")
def prices(staff: Staff = Depends(approved_admin)) -> Dict[str, Any]:
    """The price list the hospital's system synced (read-only here; the
    consultation price is also editable in Settings, PATCH /hospital)."""
    with session_scope(staff.hospital_id) as session:
        return pricing.price_list(session, session.get(Hospital, staff.hospital_id))
