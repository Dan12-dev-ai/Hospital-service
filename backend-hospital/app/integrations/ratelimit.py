"""Sliding-window rate limits, kept in this process's memory (the API runs
one process; like the sign-up limit in app/api/onboarding.py)."""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from typing import Deque, Optional

#: Keys tracked per limiter; the least recently seen are forgotten first.
TRACKED = 10_000


class Limiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit, self.window = limit, window_seconds
        self._hits: "OrderedDict[str, Deque[float]]" = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, key: str, now: Optional[float] = None) -> Optional[int]:
        """Count a request. None if allowed; else the seconds to wait (Retry-After)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.pop(key, None) or deque()
            self._hits[key] = hits
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1, math.ceil(hits[0] + self.window - now))
            hits.append(now)
            while len(self._hits) > TRACKED:
                self._hits.popitem(last=False)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


#: Token requests: per caller address and per client_id.
TOKENS_PER_ADDRESS = Limiter(30, 60)
TOKENS_PER_CLIENT = Limiter(20, 60)
#: API calls per client (every endpoint but the token endpoint).
REQUESTS_PER_CLIENT = Limiter(60, 60)


def reset_all() -> None:
    for limiter in (TOKENS_PER_ADDRESS, TOKENS_PER_CLIENT, REQUESTS_PER_CLIENT):
        limiter.reset()
