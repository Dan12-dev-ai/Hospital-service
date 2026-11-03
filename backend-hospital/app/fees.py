"""Endod's service fee, as this service applies it (docs/integrations.md,
"Charges"; the platform's docs/service-fee.md).

The patient pays Endod a service fee on every payment for a hospital
service: a booking (the platform adds it) and every charge made through the
integration API (added here). The super admin sets it on the patient
platform, the single source of truth, which announces it on the bus:

``fees.updated`` ``{"version", "enabled", "flat_santim", "percent_bp", "currency", "updated_at"}``

on every change, at the platform worker's start and every 6 hours. Only a
newer (or the same) version replaces the one kept in ``endod_fee_settings``,
so an old event arriving late changes nothing, and fees are still quoted
while the platform is unreachable. Before the first one ever arrives, the
default is ``HOSPITAL_DEFAULT_SERVICE_FEE_SANTIM`` (2500: 25 birr flat).

The rule (the same as the platform's fee_settings.fee_for):
fee = flat + round_half_up(subtotal x percent_bp / 10000) santim; none when
switched off or on a subtotal of 0. One fee per charge.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import AwareDatetime, BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import ensure_aware, utcnow
from app.eventbus import PermanentEventError
from app.models import EndodFeeSettings

logger = logging.getLogger("hospital.fees")

ROW_ID = 1


@dataclass(frozen=True)
class Fee:
    enabled: bool
    flat_santim: int
    percent_bp: int
    #: 0: the default (nothing received from the platform yet).
    version: int
    updated_at: Optional[datetime] = None

    def on(self, subtotal: int) -> int:
        return fee_for(subtotal, self)


def default() -> Fee:
    return Fee(enabled=True, flat_santim=max(0, get_settings().DEFAULT_SERVICE_FEE_SANTIM), percent_bp=0, version=0)


def current(session: Session) -> Fee:
    """The settings in force: the platform's last announcement, else the default."""
    row = session.get(EndodFeeSettings, ROW_ID)
    if row is None:
        return default()
    return Fee(enabled=row.enabled, flat_santim=row.flat_santim, percent_bp=row.percent_bp, version=row.version,
               updated_at=ensure_aware(row.updated_at) if row.updated_at else None)


def fee_for(subtotal: int, fee: Fee) -> int:
    """Endod's fee in santim on one payment of ``subtotal`` santim."""
    if not fee.enabled or subtotal <= 0:
        return 0
    return fee.flat_santim + (subtotal * fee.percent_bp + 5_000) // 10_000


def describe(fee: Fee) -> Dict[str, Any]:
    """The fee as the integration API shows it (birr as text, like prices)."""
    from app.validation import birr

    example = 20_000
    return {"currency": "ETB", "enabled": fee.enabled, "flat": birr(fee.flat_santim),
            "percent": f"{fee.percent_bp / 100:.2f}", "rule": "one fee per charge or booking: flat + percent of the "
                                                            "subtotal, rounded to the santim; none on 0",
            "example": {"subtotal": birr(example), "service_fee": birr(fee_for(example, fee)),
                        "total": birr(example + fee_for(example, fee))},
            "updated_at": fee.updated_at.isoformat() if fee.updated_at else None}


class _Updated(BaseModel):
    version: int = Field(ge=0, strict=True)
    enabled: bool
    flat_santim: int = Field(ge=0, le=100_000, strict=True)
    percent_bp: int = Field(ge=0, le=2_000, strict=True)
    currency: str = Field(default="ETB", pattern=r"^ETB$")
    updated_at: Optional[AwareDatetime] = None


def on_fees_updated(session: Session, payload: Dict[str, Any]) -> None:
    """``fees.updated`` from the patient platform: keep it unless older than the one kept."""
    try:
        update = _Updated.model_validate(payload)
    except ValidationError as exc:
        raise PermanentEventError(str(exc).splitlines()[0]) from exc
    row = session.get(EndodFeeSettings, ROW_ID, with_for_update=True)
    if row is not None and update.version < row.version:
        logger.info("fees_update_ignored version=%s kept=%s", update.version, row.version)
        return
    if row is None:
        row = EndodFeeSettings(id=ROW_ID)
        session.add(row)
    row.version, row.enabled = update.version, update.enabled
    row.flat_santim, row.percent_bp = update.flat_santim, update.percent_bp
    row.updated_at, row.received_at = update.updated_at, utcnow()
    logger.info("fees_updated version=%s enabled=%s flat=%s bp=%s", update.version, update.enabled,
                update.flat_santim, update.percent_bp)


HANDLERS = {"fees.updated": on_fees_updated}
