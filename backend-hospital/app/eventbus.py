"""Events between this service and the Endod patient platform (Redis Streams).

Two streams, one per direction (the contract is in docs/events.md):

* ``endod:hospital``: what this service publishes (hospital listings,
  decisions on bookings);
* ``endod:patient``: what the patient platform publishes (bookings,
  cancellations), read here with the consumer group ``hospital-service``.

Delivery is at least once, and handling is exactly once:

* **Outbox.** :func:`emit` writes the event into ``outbox_events`` in the same
  transaction as the change it describes. :func:`publish_pending` sends
  unsent rows to Redis, in order, from one publisher at a time (a database
  lock), and marks them sent only after Redis (and, when configured, a
  replica) has them. If Redis is down, events wait in the database.
  Payloads carry clinical data in plain text (the platform needs it), so a
  sent row is deleted after :data:`KEEP_PUBLISHED_FOR` (:func:`housekeeping`):
  the outbox never becomes a plain copy of the encrypted records.
* **Inbox.** Each received event's id is recorded in ``processed_events`` in
  the same transaction as its effect, so a redelivered event is skipped.
* **Retries.** A failed event stays pending in the group and is claimed again
  after :data:`RETRY_AFTER_MS`; after :data:`MAX_DELIVERIES` attempts, or at
  once for a malformed event (:class:`PermanentEventError`), it goes to
  ``endod:dead-letter`` for a person to look at: its id, type, source, time,
  the error (at most :data:`DEAD_LETTER_ERROR_CHARS`) and a redacted payload
  (field names, and the values of ``*_id`` fields only: no clinical data, no
  names or phones), in a stream capped at :data:`DEAD_LETTER_MAXLEN` entries.

**Plain text in Redis.** Events carry clinical data in plain text (the
receiving side needs it), and Redis is not encrypted at rest. An event is
plain text in Redis while it is in flight: from when it is sent until every
consumer group on its stream has acknowledged it. Then it is deleted
(:func:`purge_acknowledged`: on ``endod:hospital`` for the events this service
produces, now and then; on ``endod:patient`` right after this service
acknowledges, once every group there has). An event no group ever reads is
trimmed after :data:`KEEP_STREAM_FOR` at the latest.

Redis is reached through Sentinel when ``HOSPITAL_REDIS_SENTINELS`` is set (the
current master is looked up on every connect, so a failover is followed), or
directly through ``HOSPITAL_REDIS_URL``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import socket
import time
from datetime import timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import redis
from redis.sentinel import Sentinel
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import ensure_aware, platform_session, session_scope, utcnow
from app.models import OutboxEvent, ProcessedEvent
from app.validation import checked_dedan_id

logger = logging.getLogger("hospital.events")

SOURCE = "hospital-service"
STREAM_OUT = "endod:hospital"
STREAM_IN = "endod:patient"
DEAD_LETTER = "endod:dead-letter"
GROUP = "hospital-service"
#: A pending event not acknowledged for this long is retried.
RETRY_AFTER_MS = 30_000
MAX_DELIVERIES = 5
#: Stream entries older than this are trimmed (well past any retry), acknowledged or not.
KEEP_STREAM_FOR = timedelta(days=7)
#: The dead-letter stream keeps about this many entries.
DEAD_LETTER_MAXLEN = 10_000
DEAD_LETTER_ERROR_CHARS = 500
DEAD_LETTER_PAYLOAD_CHARS = 2_000
#: Handled-event ids are deleted after this.
KEEP_RECORDS_FOR = timedelta(days=30)
#: Sent outbox rows (plain clinical payloads) are deleted after this.
KEEP_PUBLISHED_FOR = timedelta(hours=24)
#: Postgres advisory lock id: one publisher at a time keeps events in order.
_PUBLISH_LOCK = 0x45_4E_44_4F_44  # "ENDOD"

Handler = Callable[[Session, Dict[str, Any]], None]


class PermanentEventError(ValueError):
    """The event can never be handled (malformed): dead-letter it at once."""


class RetryLater(RuntimeError):
    """The event cannot be handled yet (e.g. it refers to one not received yet)."""


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
        sentinel_password = settings.REDIS_SENTINEL_PASSWORD
        sentinel = Sentinel(sentinels, socket_timeout=5,
                            sentinel_kwargs={"password": sentinel_password} if sentinel_password else None)
        return sentinel.master_for(settings.REDIS_SENTINEL_MASTER, password=settings.REDIS_PASSWORD,
                                   db=settings.REDIS_DB, **common)
    if settings.REDIS_URL:
        return redis.Redis.from_url(settings.REDIS_URL, **common)
    return None


# --- publishing ------------------------------------------------------------------------

def emit(session: Session, event_type: str, payload: Dict[str, Any]) -> None:
    """Queue an event; it is sent once the caller's transaction commits.

    An Endod ID in the payload must be in its stored form (DE + 6 digits):
    a free-typed value is never sent (ValueError, and the change rolls back).
    """
    checked_dedan_id(payload.get("dedan_id"))
    session.add(OutboxEvent(type=event_type, payload=json.dumps(payload, default=str, ensure_ascii=False)))


def _publisher_lock(session: Session) -> bool:
    """Only one publisher at a time (on Postgres): otherwise two workers could
    send rows out of order. SQLite has one writer anyway."""
    if session.get_bind().dialect.name != "postgresql":
        return True
    return bool(session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _PUBLISH_LOCK}))


def publish_pending(client: redis.Redis, batch: int = 100) -> int:
    """Send unsent events in order. Returns how many were sent."""
    min_replicas = get_settings().REDIS_MIN_REPLICAS
    # The outbox holds every hospital's events: only the platform role reads it.
    with platform_session() as session:
        if not _publisher_lock(session):
            return 0  # another worker is publishing
        rows = list(session.scalars(
            select(OutboxEvent).where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at, OutboxEvent.id).limit(batch)
        ))
        if not rows:
            return 0
        pipe = client.pipeline(transaction=False)
        for row in rows:
            pipe.xadd(STREAM_OUT, {
                "id": row.id,
                "type": row.type,
                "source": SOURCE,
                "occurred_at": ensure_aware(row.created_at).astimezone(timezone.utc).isoformat(),
                "payload": row.payload,
            })
        pipe.execute()
        if min_replicas > 0:
            # Redis replication is asynchronous: wait until a replica has the
            # events, or a failover could lose them after we marked them sent.
            acknowledged = client.wait(min_replicas, 2000)
            if acknowledged < min_replicas:
                raise redis.ConnectionError(f"only {acknowledged} replica(s) confirmed the events")
        now = utcnow()
        for row in rows:
            row.published_at = now
        # If this commit fails, the rows are sent again and the receiver's
        # inbox drops the duplicates.
        return len(rows)


def purge_published(now=None) -> int:
    """Delete outbox rows sent more than :data:`KEEP_PUBLISHED_FOR` ago (their
    payloads are plain text). Unsent rows stay until sent. Returns how many."""
    cutoff = (now or utcnow()) - KEEP_PUBLISHED_FOR
    with platform_session() as session:
        return session.execute(delete(OutboxEvent).where(OutboxEvent.published_at.is_not(None),
                                                         OutboxEvent.published_at < cutoff)).rowcount or 0


#: Deletes the entries every consumer group has acknowledged, in one atomic
#: step: Redis runs a script alone, so no group can be created (or read, or
#: acknowledge) between looking at the groups and trimming. For each group
#: the boundary is its oldest pending entry, or else the entry after the last
#: one delivered to it; everything older than the lowest boundary goes.
_PURGE_SCRIPT = """
local ok, groups = pcall(redis.call, 'XINFO', 'GROUPS', KEYS[1])
if not ok or #groups == 0 then return 0 end
-- Ids are compared as numbers but written back from their own digits (Lua
-- 5.1 cannot format a 13-digit number with %d everywhere).
local best_ms, best_seq, best_ms_text = nil, nil, nil
for _, group in ipairs(groups) do
  local info = {}
  for i = 1, #group, 2 do info[group[i]] = group[i + 1] end
  local ms_text, seq_text, seq
  if tonumber(info['pending']) > 0 then
    local summary = redis.call('XPENDING', KEYS[1], info['name'])
    ms_text, seq_text = string.match(summary[2], '^(%d+)-(%d+)$')
    seq = tonumber(seq_text)
  else
    ms_text, seq_text = string.match(info['last-delivered-id'], '^(%d+)-(%d+)$')
    seq = tonumber(seq_text) + 1
  end
  local ms = tonumber(ms_text)
  if best_ms == nil or ms < best_ms or (ms == best_ms and seq < best_seq) then
    best_ms, best_seq, best_ms_text = ms, seq, ms_text
  end
end
if best_ms == 0 and best_seq <= 1 then return 0 end
return redis.call('XTRIM', KEYS[1], 'MINID', best_ms_text .. '-' .. string.format('%.0f', best_seq))
"""


def purge_acknowledged(client: redis.Redis, stream: str) -> int:
    """Delete the entries of ``stream`` that every consumer group on it has
    acknowledged (read, and no longer pending), atomically (a Lua script). A
    stream without a group keeps its entries (nobody has read them). Returns
    how many were deleted.

    Assumptions (docs/events.md): an entry a consumer still holds is in its
    group's pending list, so it is kept; consumers are never removed with
    XGROUP DELCONSUMER while they hold entries (this service never removes
    any: a dead process's entries are claimed with XAUTOCLAIM), since that
    drops them from the pending list unacknowledged. A group created later
    from ``0`` sees only what no group had finished with by then."""
    return int(client.eval(_PURGE_SCRIPT, 1, stream) or 0)


def housekeeping(client: redis.Redis) -> None:
    """Trim old stream entries and delete old records (run now and then)."""
    purge_acknowledged(client, STREAM_OUT)
    purge_acknowledged(client, STREAM_IN)
    cutoff_ms = int((time.time() - KEEP_STREAM_FOR.total_seconds()) * 1000)
    client.xtrim(STREAM_OUT, minid=f"{cutoff_ms}-0", approximate=True)
    purge_published()
    with platform_session() as session:
        session.execute(delete(ProcessedEvent).where(ProcessedEvent.processed_at < utcnow() - KEEP_RECORDS_FOR))


# --- consuming ---------------------------------------------------------------------------

def ensure_group(client: redis.Redis) -> None:
    try:
        client.xgroup_create(STREAM_IN, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


#: Unique per process: two workers on one host must not share a name.
_CONSUMER = f"{socket.gethostname()}-{os.getpid()}-{secrets.token_hex(3)}"


def consumer_name() -> str:
    return _CONSUMER


def consume_once(client: redis.Redis, handlers: Dict[str, Handler], consumer: Optional[str] = None,
                 block_ms: int = 2000, count: int = 50) -> int:
    """Handle stalled events, then new ones. Returns how many were handled."""
    consumer = consumer or consumer_name()
    messages: List[Tuple[str, Dict[str, str]]] = []
    try:
        claimed = client.xautoclaim(STREAM_IN, GROUP, consumer, min_idle_time=RETRY_AFTER_MS,
                                    start_id="0-0", count=count)
    except redis.ResponseError as exc:
        if "NOGROUP" not in str(exc):
            raise
        # First run, or a Redis that restarted empty: create the group (from
        # the start of the stream, so nothing already there is skipped).
        ensure_group(client)
        claimed = (None, [], [])
    for message_id, fields in claimed[1]:
        if fields:
            messages.append((message_id, fields))
        else:
            # The entry was trimmed while pending (Redis 6.2 still lists it).
            client.xack(STREAM_IN, GROUP, message_id)
    fresh = client.xreadgroup(GROUP, consumer, {STREAM_IN: ">"}, count=count, block=block_ms)
    for _stream, entries in fresh or []:
        messages.extend(entries)
    for message_id, fields in messages:
        _handle(client, message_id, fields, handlers)
    if messages:
        # Acknowledged: delete what every group on the stream is done with.
        purge_acknowledged(client, STREAM_IN)
    return len(messages)


def _already_processed(event_id: str) -> bool:
    with session_scope() as session:
        return session.get(ProcessedEvent, event_id) is not None


_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def safe_error(exc: BaseException) -> str:
    """What failed, for Redis and logs: the exception's class and the first
    line of its message. A database error gives only the driver's primary
    message (``diag.message_primary``): never the statement, its parameters
    or the DETAIL line (which can quote row values)."""
    if isinstance(exc, DBAPIError):
        orig = exc.orig
        primary = getattr(getattr(orig, "diag", None), "message_primary", None)
        if not primary:
            primary = str(orig).strip().splitlines()[0] if str(orig).strip() else ""
        message = f"{type(orig).__name__}: {primary}"
    else:
        text_ = str(exc).strip()
        message = f"{type(exc).__name__}: {text_.splitlines()[0]}" if text_ else type(exc).__name__
    return message[:DEAD_LETTER_ERROR_CHARS]


def redacted_payload(raw: Optional[str]) -> str:
    """The payload's shape without its data: field names, with the values of
    identifier fields (``*_id``, short, id-like) and the type of everything
    else. Nothing clinical, no names or phones."""
    try:
        payload = json.loads(raw or "{}")
    except ValueError:
        return json.dumps({"unparseable_bytes": len(raw or "")})
    if not isinstance(payload, dict):
        return json.dumps({"not_an_object": type(payload).__name__})
    shown = {}
    for key in sorted(payload)[:50]:
        value = payload[key]
        if (str(key).endswith("_id") or key == "id") and isinstance(value, str) and _SAFE_ID.match(value):
            shown[str(key)[:64]] = value
        else:
            shown[str(key)[:64]] = f"<{type(value).__name__}>"
    return json.dumps(shown)[:DEAD_LETTER_PAYLOAD_CHARS]


def _dead_letter(client: redis.Redis, message_id: str, fields: Dict[str, str], why: str) -> None:
    """Keep what a person needs to find the event again, never its data."""
    entry = {name: str(fields.get(name) or "")[:128] for name in ("id", "type", "source", "occurred_at")}
    entry.update(stream=STREAM_IN, group=GROUP, message_id=message_id, error=why[:DEAD_LETTER_ERROR_CHARS],
                 payload_redacted=redacted_payload(fields.get("payload")))
    client.xadd(DEAD_LETTER, entry, maxlen=DEAD_LETTER_MAXLEN, approximate=True)
    client.xack(STREAM_IN, GROUP, message_id)
    logger.error("event_dead_lettered type=%s id=%s error=%s", entry["type"], entry["id"],
                 why[:DEAD_LETTER_ERROR_CHARS])


def _handle(client: redis.Redis, message_id: str, fields: Dict[str, str], handlers: Dict[str, Handler]) -> None:
    event_id, event_type = fields.get("id"), fields.get("type")
    handler = handlers.get(event_type or "")
    if not event_id or handler is None:
        # Not for us (or malformed): acknowledge so it does not block the group.
        logger.info("event_ignored type=%s id=%s", event_type, event_id)
        client.xack(STREAM_IN, GROUP, message_id)
        return
    try:
        try:
            payload = json.loads(fields.get("payload") or "{}")
        except ValueError as exc:
            raise PermanentEventError("payload is not JSON") from exc
        if not isinstance(payload, dict):
            raise PermanentEventError("payload is not an object")
        # Events from the platform name their hospital in the payload and may
        # concern any of them: handlers act for Endod (platform scope).
        with platform_session() as session:
            if session.get(ProcessedEvent, event_id) is None:
                handler(session, payload)
                session.add(ProcessedEvent(id=event_id, type=event_type))
        client.xack(STREAM_IN, GROUP, message_id)
    except PermanentEventError as exc:
        _dead_letter(client, message_id, fields, f"invalid: {safe_error(exc)}")
    except Exception as exc:  # noqa: BLE001 -- retried, then dead-lettered
        if isinstance(exc, IntegrityError) and _already_processed(event_id):
            # Another worker handled the same event at the same moment.
            client.xack(STREAM_IN, GROUP, message_id)
            return
        if isinstance(exc, RetryLater):
            logger.info("event_deferred type=%s id=%s: %s", event_type, event_id, safe_error(exc))
        elif isinstance(exc, DBAPIError):
            # No traceback: a database error's text can carry a DETAIL with row values.
            logger.error("event_failed type=%s id=%s error=%s", event_type, event_id, safe_error(exc))
        else:
            logger.exception("event_failed type=%s id=%s error=%s", event_type, event_id, safe_error(exc))
        if _deliveries(client, message_id) >= MAX_DELIVERIES:
            _dead_letter(client, message_id, fields, safe_error(exc))


def _deliveries(client: redis.Redis, message_id: str) -> int:
    pending = client.xpending_range(STREAM_IN, GROUP, min=message_id, max=message_id, count=1)
    return int(pending[0]["times_delivered"]) if pending else 0
