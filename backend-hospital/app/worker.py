"""The event worker: ``python -m app.worker``.

Sends this service's queued events to the Endod platform and handles the
platform's events, in a loop. Survives Redis being down or failing over: it
waits and reconnects (through Sentinel, to whichever server is now master);
events wait in the database meanwhile.
"""

from __future__ import annotations

import logging
import signal
import time

import redis

from app import bookings, eventbus

logger = logging.getLogger("hospital.worker")
_running = True


def _stop(*_args) -> None:
    global _running
    _running = False


#: Seconds between the slower chores.
EXPIRE_EVERY = 60
HOUSEKEEPING_EVERY = 3600
_last = {"expire": 0.0, "housekeeping": 0.0}


def run_once(client: redis.Redis, now: float | None = None) -> int:
    """One round: send what is queued, handle what arrived, and now and then
    decline unapproved video visits and clean up. Returns the work done."""
    now = time.monotonic() if now is None else now
    work = 0
    if now - _last["expire"] >= EXPIRE_EVERY:
        work += bookings.expire_unapproved()
        _last["expire"] = now
    work += eventbus.publish_pending(client)
    work += eventbus.consume_once(client, bookings.HANDLERS, block_ms=1000)
    if now - _last["housekeeping"] >= HOUSEKEEPING_EVERY:
        eventbus.housekeeping(client)
        _last["housekeeping"] = now
    return work


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    backoff = 1.0
    client = None
    while _running:
        try:
            if client is None:
                client = eventbus.connect()
                if client is None:
                    logger.error("No Redis configured (HOSPITAL_REDIS_URL or HOSPITAL_REDIS_SENTINELS).")
                    time.sleep(30)
                    continue
            run_once(client)
            backoff = 1.0
        except (redis.ConnectionError, redis.TimeoutError, redis.sentinel.MasterNotFoundError) as exc:
            logger.warning("redis_unavailable %s; retrying in %.0fs", exc, backoff)
            client = None
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
        except Exception:  # noqa: BLE001 -- keep the worker alive; the event is retried
            logger.exception("worker_round_failed")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
    logger.info("worker_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
