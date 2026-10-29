"""Periodic clean-up for patient history (run by the worker)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select

from app import files, onboarding, queues, sharing
from app.db import platform_session, utcnow
from app.models import (
    DeliveryStatus, ImportBatch, IntegrationAssertion, IntegrationIdempotency, IntegrationRequest, RecordFile,
    WebhookDelivery,
)

#: Uploads never attached to a record (an abandoned form or import preview).
KEEP_UNATTACHED_FOR = timedelta(days=2)
KEEP_IMPORT_PLANS_FOR = timedelta(days=30)
#: The integration API's request log and webhook delivery log.
KEEP_INTEGRATION_LOGS_FOR = timedelta(days=30)
KEEP_IDEMPOTENCY_FOR = timedelta(hours=24)


def run() -> int:
    """End expired shares, cancel stale queue entries, delete abandoned uploads
    and old import plans. Returns the work done."""
    now = utcnow()
    with platform_session() as session:  # every hospital's, for the worker
        work = sharing.expire(session)
        # Demo slots held by applications not submitted in time.
        work += onboarding.release_stale(session)
        work += queues.cancel_stale(session, now)
        for row in session.scalars(select(RecordFile).where(
                RecordFile.record_id.is_(None), RecordFile.created_at < now - KEEP_UNATTACHED_FOR)):
            files.delete(row.hospital_id, row.id)
            session.delete(row)
            work += 1
        session.execute(delete(ImportBatch).where(ImportBatch.created_at < now - KEEP_IMPORT_PLANS_FOR))
        # The integration API: logs after 30 days, used assertions once expired, idempotent answers after a day.
        work += session.execute(delete(IntegrationRequest).where(
            IntegrationRequest.at < now - KEEP_INTEGRATION_LOGS_FOR)).rowcount or 0
        session.execute(delete(WebhookDelivery).where(
            WebhookDelivery.status != DeliveryStatus.PENDING, WebhookDelivery.created_at < now - KEEP_INTEGRATION_LOGS_FOR))
        session.execute(delete(IntegrationAssertion).where(IntegrationAssertion.expires_at < now))
        session.execute(delete(IntegrationIdempotency).where(
            IntegrationIdempotency.created_at < now - KEEP_IDEMPOTENCY_FOR))
    return work
