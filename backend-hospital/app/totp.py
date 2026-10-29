"""TOTP (RFC 6238): 6 digits, 30-second steps, SHA-1, as Google Authenticator expects.

The same as TenaCare's (app/totp.py there): one step either side of now, and a
code (and any older one) accepted once: the caller stores the step returned.
"""

from __future__ import annotations

import hmac
import time
from typing import Optional

import pyotp

ISSUER = "Endod Hospital"
DIGITS = 6
INTERVAL = 30
#: Steps accepted either side of now (clock drift on the phone).
WINDOW = 1


def new_secret() -> str:
    """160 random bits, base32 (what authenticator apps expect)."""
    return pyotp.random_base32(length=32)


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret, digits=DIGITS, interval=INTERVAL).provisioning_uri(name=email, issuer_name=ISSUER)


def _clock() -> float:
    """Seconds since the epoch (tests replace it)."""
    return time.time()


def current_step(now: Optional[float] = None) -> int:
    return int((_clock() if now is None else now) // INTERVAL)


def code_at(secret: str, step: int) -> str:
    return pyotp.HOTP(secret, digits=DIGITS).at(step)


def normalize(code: str) -> str:
    return "".join(ch for ch in code if not ch.isspace())


def verify(secret: str, code: str, last_step: Optional[int], now: Optional[float] = None) -> Optional[int]:
    """The step ``code`` belongs to, if it is valid within the window and newer
    than ``last_step`` (so each code, and any older one, is accepted only once);
    else None. The caller stores the step it returns."""
    code = normalize(code)
    if len(code) != DIGITS or not (code.isascii() and code.isdigit()):
        return None
    now_step = current_step(now)
    matched: Optional[int] = None
    # Every candidate is compared (constant work), the newest match wins.
    for step in range(now_step - WINDOW, now_step + WINDOW + 1):
        if hmac.compare_digest(code_at(secret, step), code) and (last_step is None or step > last_step):
            matched = step
    return matched
