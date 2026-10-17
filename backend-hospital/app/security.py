"""Passwords and session tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Optional

# scrypt parameters (memory-hard; ~16 MB per hash).
_N, _R, _P = 2**14, 8, 1
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 200


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (
        _N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def password_problem(password: str) -> Optional[str]:
    """The reason a password is not acceptable, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    if not any(c.islower() for c in password) or not any(c.isupper() for c in password):
        return "Password must include both upper and lower case letters."
    return None


def temporary_password() -> str:
    """A one-time password an admin hands to a new staff member."""
    while True:
        candidate = secrets.token_urlsafe(12)
        if password_problem(candidate) is None:
            return candidate


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
