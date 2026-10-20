"""Events between this service and the Endod patient platform (Redis Streams).

Two streams, one per direction:

* ``endod:hospital``: what this service publishes (hospital listings,
  decisions on bookings);
* ``endod:patient``: what the patient platform publishes (bookings,
  cancellations), read here with the consumer group ``hospital-service``.

Delivery is at least once, and handling is exactly once:

* **Outbox.** :func:`emit` writes the event into ``outbox_events`` in the same
  transaction as the change it describes. :func:`publish_pending` sends
  unsent rows to Redis. If Redis is down, events wait in the database; a
  change is never saved without its event, or announced without being saved.
* **Inbox.** Each received event's id is recorded in ``processed_events`` in
  the same transaction as its effect, so a redelivered event is skipped.
* **Retries.** A failed event stays pending in the group and is claimed again
  after :data:`RETRY_AFTER_MS`; after :data:`MAX_DELIVERIES` attempts it goes
  to ``endod:dead-letter`` for a person to look at.

Redis is reached through Sentinel when ``HOSPITAL_REDIS_SENTINELS`` is set (the
current master is looked up on every connect, so a failover is followed), or
directly through ``HOSPITAL_REDIS_URL``.
"""

from __future__ import annotations

import json
import logging
import socket
from datetime import timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import redis
from redis.sentinel import Sentinel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import ensure_aware, session_scope, utcnow
from app.models import OutboxEvent, ProcessedEvent

logger = logging.getLogger("hospital.events")

SOURCE = "hospital-service"
STREAM_OUT = "endod:hospital"
STREAM_IN = "endod:patient"
DEAD_LETTER = "endod:dead-letter"
GROUP = "hospital-service"
#: A pending event not acknowledged for this long is retried.
RETRY_AFTER_MS = 30_000
MAX_DELIVERIES = 5
#: Streams are trimmed to about this many entries.
STREAM_MAXLEN = 100_000

Handler = Callable[[Session, Dict[str, Any]], None]


# --- connection -------------------------------------------------------------------

def connect() -> Optional[redis.Redis]:
    """A client for the current Redis master, or None when no Redis is configured."""
    settings = get_settings()
    common = {"decode_responses": True, "socket_timeout": 5, "socket_connect_timeout": 5,
              "health_check_interval": 30}
    if settings.REDIS_SENTINELS:
        sentinels = []
        for entry in settings.REDIS_SENTINELS:
            host, _, port = entry.rpartition(":")
            sentinels.append((host, int(port or 26379)))
        sentinel = Sentinel(sentinels, socket_timeout=5, sentinel_kwargs={"password": settings.REDIS_PASSWORD}
                            if settings.REDIS_PASSWORD else None)
        return sentinel.master_for(settings.REDIS_SENTINEL_MASTER, password=settings.REDIS_PASSWORD,
                                   db=settings.REDIS_DB, **common)
    if settings.REDIS_URL:
        return redis.Redis.from_url(settings.REDIS_URL, **common)
    return None


# --- publishing ------------------------------------------------------------------------

def emit(session: Session, event_type: str, payload: Dict[str, Any]) -> None:
    """Queue an event; it is sent once the caller's transaction commits."""
    session.add(OutboxEvent(type=event_type, payload=json.dumps(payload, default=str, ensure_ascii=False)))


def publish_pending(client: redis.Redis, batch: int = 100) -> int:
    """Send unsent events in order. Returns how many were sent."""
    sent = 0
    with session_scope() as session:
        rows = session.scalars(
            select(OutboxEvent).where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at, OutboxEvent.id).limit(batch)
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            client.xadd(STREAM_OUT, {
                "id": row.id,
                "type": row.type,
                "source": SOURCE,
                "occurred_at": ensure_aware(row.created_at).astimezone(timezone.utc).isoformat(),
                "payload": row.payload,
            }, maxlen=STREAM_MAXLEN, approximate=True)
            # Sent before this commit: if the commit fails, the row is sent
            # again later, and the receiver's inbox drops the duplicate.
            row.published_at = utcnow()
            sent += 1
    return sent


# --- consuming ---------------------------------------------------------------------------

def ensure_group(client: redis.Redis) -> None:
    try:
        client.xgroup_create(STREAM_IN, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def consumer_name() -> str:
    return f"{socket.gethostname()}"


def consume_once(client: redis.Redis, handlers: Dict[str, Handler], consumer: Optional[str] = None,
                 block_ms: int = 2000, count: int = 50) -> int:
    """Handle stalled events, then new ones. Returns how many were handled."""
    consumer = consumer or consumer_name()
    ensure_group(client)
    messages: List[Tuple[str, Dict[str, str]]] = []
    claimed = client.xautoclaim(STREAM_IN, GROUP, consumer, min_idle_time=RETRY_AFTER_MS,
                                start_id="0-0", count=count)
    messages.extend(m for m in claimed[1] if m and m[1])
    fresh = client.xreadgroup(GROUP, consumer, {STREAM_IN: ">"}, count=count, block=block_ms)
    for _stream, entries in fresh or []:
        messages.extend(entries)
    for message_id, fields in messages:
        _handle(client, message_id, fields, handlers)
    return len(messages)


def _handle(client: redis.Redis, message_id: str, fields: Dict[str, str], handlers: Dict[str, Handler]) -> None:
    event_id, event_type = fields.get("id"), fields.get("type")
    handler = handlers.get(event_type or "")
    if not event_id or handler is None:
        # Not for us (or malformed): acknowledge so it does not block the group.
        logger.info("event_ignored type=%s id=%s", event_type, event_id)
        client.xack(STREAM_IN, GROUP, message_id)
        return
    try:
        payload = json.loads(fields.get("payload") or "{}")
        with session_scope() as session:
            if session.get(ProcessedEvent, event_id) is None:
                handler(session, payload)
                session.add(ProcessedEvent(id=event_id, type=event_type))
        client.xack(STREAM_IN, GROUP, message_id)
    except IntegrityError:
        # Another worker handled the same event at the same moment.
        client.xack(STREAM_IN, GROUP, message_id)
    except Exception:  # noqa: BLE001 -- any failure is retried, then dead-lettered
        logger.exception("event_failed type=%s id=%s", event_type, event_id)
        if _deliveries(client, message_id) >= MAX_DELIVERIES:
            client.xadd(DEAD_LETTER, {**fields, "stream": STREAM_IN, "group": GROUP}, maxlen=STREAM_MAXLEN,
                        approximate=True)
            client.xack(STREAM_IN, GROUP, message_id)
            logger.error("event_dead_lettered type=%s id=%s", event_type, event_id)


def _deliveries(client: redis.Redis, message_id: str) -> int:
    pending = client.xpending_range(STREAM_IN, GROUP, min=message_id, max=message_id, count=1)
    return int(pending[0]["times_delivered"]) if pending else 0

