"""Sliding-window counters, kept in this process's memory (the integrations
service runs one process; like the sign-up limit in app/api/onboarding.py).

Bounded without resetting under churn: a key is forgotten only once its
window has passed. When every tracked key is still live, a new key is
refused (fail closed) instead of evicting a live one, so an attacker cannot
flush someone else's count by spraying new keys. The global token limit in
front keeps the number of live keys far below the bound (at most
``TOKENS_GLOBAL.limit`` new keys per window).
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from typing import Deque, Optional

#: Keys tracked per counter.
TRACKED = 100_000


class Limiter:
    def __init__(self, limit: int, window_seconds: float, tracked: int = TRACKED):
        self.limit, self.window, self.tracked = limit, window_seconds, tracked
        #: key -> hit times, least recently hit first.
        self._hits: "OrderedDict[str, Deque[float]]" = OrderedDict()
        self._lock = threading.Lock()

    def _live(self, key: str, now: float, create: bool) -> Optional[Deque[float]]:
        hits = self._hits.get(key)
        if hits is None:
            if not create:
                return None
            if len(self._hits) >= self.tracked:
                # Forget only keys whose window has passed (the least recently hit come first).
                for old in list(self._hits):
                    newest = self._hits[old]
                    if newest and newest[-1] > now - self.window:
                        break
                    del self._hits[old]
                if len(self._hits) >= self.tracked:
                    return None  # full of live keys: refuse rather than forget one
            hits = self._hits[key] = deque()
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        return hits

    def _wait(self, hits: Deque[float], now: float) -> int:
        return max(1, math.ceil(hits[0] + self.window - now)) if hits else math.ceil(self.window)

    def hit(self, key: str, now: Optional[float] = None) -> Optional[int]:
        """Count a request. None if allowed; else the seconds to wait (Retry-After)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._live(key, now, create=True)
            if hits is None:
                return math.ceil(self.window)
            if len(hits) >= self.limit:
                return self._wait(hits, now)
            hits.append(now)
            self._hits.move_to_end(key)
            return None

    def note(self, key: str, now: Optional[float] = None) -> None:
        """Count an event (a failure) without asking whether it is allowed."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._live(key, now, create=True)
            if hits is not None:
                hits.append(now)
                self._hits.move_to_end(key)

    def blocked(self, key: str, now: Optional[float] = None) -> Optional[int]:
        """The seconds to wait if ``limit`` events are recent, else None (counts nothing)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._live(key, now, create=False)
            if hits is not None and len(hits) >= self.limit:
                return self._wait(hits, now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


#: Token requests, checked before anything else: every caller together,
#: per address, and per client_id from one address (a client_id is public:
#: one address cannot use up another's allowance for it).
TOKENS_GLOBAL = Limiter(600, 60)
TOKENS_PER_ADDRESS = Limiter(30, 60)
TOKENS_PER_CLIENT_ADDRESS = Limiter(20, 60)
#: Failed authentications only: from one address (refused for a while), and
#: per client_id (only failed attempts get "slow down"; the right credentials
#: still work, so nobody can lock a client out).
FAILURES_PER_ADDRESS = Limiter(20, 900)
FAILURES_PER_CLIENT = Limiter(50, 900)
#: API calls per client (every endpoint but the token endpoint).
REQUESTS_PER_CLIENT = Limiter(60, 60)

ALL = (TOKENS_GLOBAL, TOKENS_PER_ADDRESS, TOKENS_PER_CLIENT_ADDRESS, FAILURES_PER_ADDRESS, FAILURES_PER_CLIENT,
       REQUESTS_PER_CLIENT)


def reset_all() -> None:
    for limiter in ALL:
        limiter.reset()
