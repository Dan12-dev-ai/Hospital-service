"""Two-step verification for every staff member: a password, then a code from
an authenticator app (TOTP, Google Authenticator), as TenaCare does it.

* **When.** Staff of a hospital Endod approved give a code at every sign-in.
  One who has none set up yet signs in with the password into an ``enroll``
  session, which only sets up the authenticator (after a temporary password
  is changed). A hospital still applying keeps password-only sign-in (as
  TenaCare's "2FA after approval"); approving it ends every session of its
  staff, so their next sign-in sets up the authenticator.
* **Codes.** pyotp TOTP (app/totp.py), one step either side of now; each code,
  and every older one, works once (``totp_last_step``). Secrets are encrypted
  at rest with the hospital's data key (app/sealing.py, app/crypto.py).
* **Recovery codes.** Ten one-time codes at set-up, shown once; only their
  keyed hashes (HMAC-SHA256 under a key derived from the master key) are kept.
* **Throttles** on every code step (sign-in, set-up, re-authentication), none
  of which ends a session: per address (``CODE_FAILURES_PER_ADDRESS``), per
  account and address (``CODE_FAILURES_PER_PAIR``), and an account-wide
  backoff (from ``CODE_BACKOFF_AFTER`` wrong codes: 30 s, doubling, at most 15
  minutes), recorded on the account.
* **Re-authentication.** A fresh code (within ``REAUTH_MINUTES``) for
  sensitive actions: connecting systems and changing their credentials or
  settings, and resetting someone's two-step verification.
* **Reset.** An admin (with a fresh code) resets another staff member's
  authenticator; Endod's CLI does it for anyone (``reset-2fa --email``). Either
  way that staff member's sessions end and they set it up again.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update

from app import crypto, totp
from app.auth import AuthError, Staff, audit, open_session, revoke_all_sessions
from app.db import ensure_aware, session_scope, utcnow
from app.models import SessionStage, StaffRecoveryCode, StaffSession, StaffUser

INVALID_CODE = "That code is not valid. Check your authenticator app and try again."
CODE_WAIT = "Too many wrong codes for this account. Wait a few minutes, then try again."
TOO_MANY = "Too many wrong codes from this address. Try again later."
REAUTH_REQUIRED = "Confirm it is you: enter a code from your authenticator app."
CHANGE_PASSWORD_FIRST = "Change your temporary password first, then set up the authenticator."

REAUTH_MINUTES = 10
RECOVERY_CODE_COUNT = 10
#: No 0/O, 1/I/L: codes are read off paper.
_RECOVERY_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
CODE_BACKOFF_AFTER = 5
CODE_WINDOW = timedelta(minutes=15)
CODE_BACKOFF_BASE_SECONDS = 30
CODE_BACKOFF_MAX_SECONDS = 900


# --- throttles kept in this process (the API runs one) ------------------------------------------

class Failures:
    """Failures per key within a window; ``blocked`` once ``limit`` are recent."""

    def __init__(self, limit: int, window_seconds: float, tracked: int = 10_000):
        self.limit, self.window, self.tracked = limit, window_seconds, tracked
        self._hits: "OrderedDict[str, Deque[float]]" = OrderedDict()
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> Deque[float]:
        hits = self._hits.pop(key, None) or deque()
        self._hits[key] = hits
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        while len(self._hits) > self.tracked:
            self._hits.popitem(last=False)
        return hits

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key, time.monotonic())) >= self.limit

    def note(self, key: str) -> None:
        with self._lock:
            self._recent(key, time.monotonic()).append(time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


#: Wrong codes from one address, for any account, before it is refused (15 minutes).
CODE_FAILURES_PER_ADDRESS = Failures(30, 900)
#: Wrong codes for one account from one address before that pair is refused (15 minutes).
CODE_FAILURES_PER_PAIR = Failures(5, 900)


def reset_throttles() -> None:
    CODE_FAILURES_PER_ADDRESS.reset()
    CODE_FAILURES_PER_PAIR.reset()


def _pair(user_id: str, ip: str) -> str:
    return f"{user_id}|{ip}"


def backoff_seconds(failures: int) -> int:
    if failures < CODE_BACKOFF_AFTER:
        return 0
    return min(CODE_BACKOFF_BASE_SECONDS * 2 ** min(failures - CODE_BACKOFF_AFTER, 20), CODE_BACKOFF_MAX_SECONDS)


def _refused(user: StaffUser, ip: str, now: datetime) -> Optional[AuthError]:
    if CODE_FAILURES_PER_ADDRESS.blocked(ip):
        return AuthError(TOO_MANY, 429)
    if CODE_FAILURES_PER_PAIR.blocked(_pair(user.id, ip)):
        return AuthError(CODE_WAIT, 429)
    if user.code_backoff_until is not None and ensure_aware(user.code_backoff_until) > now:
        return AuthError(CODE_WAIT, 429)
    return None


def _note_failure(session, user: StaffUser, ip: str, now: datetime, step: str) -> None:
    """A wrong code: counted per address, per account and address, and against
    the account (which may start a pause). No session ends."""
    CODE_FAILURES_PER_ADDRESS.note(ip)
    CODE_FAILURES_PER_PAIR.note(_pair(user.id, ip))
    if user.code_last_failed_at is None or ensure_aware(user.code_last_failed_at) < now - CODE_WINDOW:
        user.code_failures = 0
    user.code_failures = (user.code_failures or 0) + 1
    user.code_last_failed_at = now
    seconds = backoff_seconds(user.code_failures)
    if seconds:
        user.code_backoff_until = now + timedelta(seconds=seconds)
    audit(session, user.hospital_id, user.id, "staff_code_failed",
          detail={"step": step, "failures": user.code_failures, "pause_seconds": seconds})


def _clear_failures(user: StaffUser, ip: str) -> None:
    CODE_FAILURES_PER_PAIR.clear(_pair(user.id, ip))
    user.code_failures = 0
    user.code_last_failed_at = None
    user.code_backoff_until = None


def _user(session, staff: Staff) -> StaffUser:
    user = session.scalar(select(StaffUser).where(StaffUser.id == staff.id).with_for_update())
    if user is None or not user.active:
        raise AuthError("Authentication required.")
    return user


def _end(session, session_id: str, now: datetime) -> None:
    session.execute(update(StaffSession).where(StaffSession.id == session_id).values(revoked_at=now))


# --- recovery codes -----------------------------------------------------------------------------

def new_recovery_code() -> str:
    """Like ``7k2m-q9xp-4tnw`` (12 characters, about 59 bits)."""
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def _recovery_key() -> bytes:
    return hmac.new(crypto.master_key(), b"endod-hospital|recovery-codes|v1", hashlib.sha256).digest()


def recovery_code_hash(code: str) -> str:
    normal = "".join(ch for ch in (code or "").lower() if ch.isalnum())
    return hmac.new(_recovery_key(), normal.encode(), hashlib.sha256).hexdigest()


def _replace_recovery_codes(session, user: StaffUser, now: datetime) -> List[str]:
    session.execute(delete(StaffRecoveryCode).where(StaffRecoveryCode.user_id == user.id))
    codes = [new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    for code in codes:
        session.add(StaffRecoveryCode(hospital_id=user.hospital_id, user_id=user.id,
                                      code_hash=recovery_code_hash(code), created_at=now))
    return codes


def _check_code(session, user: StaffUser, code: Optional[str], recovery_code: Optional[str],
                now: datetime) -> Optional[str]:
    """"totp" or "recovery_code" if one works (and is now used), else None."""
    if code:
        if not user.totp_secret:
            return None
        step = totp.verify(user.totp_secret, code, user.totp_last_step)
        if step is not None:
            user.totp_last_step = step
            return "totp"
        return None
    if recovery_code and len(recovery_code) <= 40:
        row = session.scalar(select(StaffRecoveryCode).where(
            StaffRecoveryCode.user_id == user.id, StaffRecoveryCode.code_hash == recovery_code_hash(recovery_code),
            StaffRecoveryCode.used_at.is_(None)).with_for_update())
        if row is not None:
            row.used_at = now
            return "recovery_code"
    return None


def recovery_codes_left(session, user_id: str) -> int:
    return session.scalar(select(func.count()).select_from(StaffRecoveryCode).where(
        StaffRecoveryCode.user_id == user_id, StaffRecoveryCode.used_at.is_(None))) or 0


# --- the code step of a sign-in ------------------------------------------------------------------

def _run(staff: Staff, work) -> Any:
    """Run ``work(session, user, now)`` in the staff member's transaction; an
    AuthError it returns (failures recorded) is raised after the commit."""
    now = utcnow()
    with session_scope(staff.hospital_id) as session:
        user = _user(session, staff)
        outcome = work(session, user, now)
    if isinstance(outcome, AuthError):
        raise outcome
    return outcome


def complete_sign_in(staff: Staff, code: Optional[str], recovery_code: Optional[str], ip: str,
                     user_agent: Optional[str]) -> Dict[str, Any]:
    if staff.stage != SessionStage.TOTP:
        raise AuthError("This sign-in does not need a code now.", 409)

    def work(session, user: StaffUser, now: datetime):
        refused = _refused(user, ip, now)
        if refused is not None:
            return refused
        method = _check_code(session, user, code, recovery_code, now)
        if method is None:
            _note_failure(session, user, ip, now, "recovery_code" if recovery_code and not code else "sign_in")
            return AuthError(INVALID_CODE, 400)
        _clear_failures(user, ip)
        _end(session, staff.session_id, now)
        opened = open_session(session, user, now, user_agent, SessionStage.FULL)
        left = recovery_codes_left(session, user.id)
        audit(session, user.hospital_id, user.id, "staff_code_accepted",
              detail={"method": method, "recovery_codes_left": left})
        return {**opened, "recovery_codes_left": left}

    return _run(staff, work)


# --- setting up the authenticator ---------------------------------------------------------------

def _enrolling(staff: Staff) -> None:
    if staff.stage != SessionStage.ENROLL:
        raise AuthError("Two-step verification is already set up.", 409)


def enrolment_start(staff: Staff) -> Dict[str, Any]:
    """The secret to add to the authenticator (a QR code's otpauth URI, and as
    text). Asking again shows the same one until it is confirmed."""
    _enrolling(staff)

    def work(session, user: StaffUser, now: datetime):
        if user.must_change_password:
            return AuthError(CHANGE_PASSWORD_FIRST, 403)
        if not user.totp_pending_secret:
            user.totp_pending_secret = totp.new_secret()
            audit(session, user.hospital_id, user.id, "staff_2fa_setup_started")
        secret = user.totp_pending_secret
        return {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, user.email),
                "issuer": totp.ISSUER, "account": user.email}

    return _run(staff, work)


def enrolment_confirm(staff: Staff, code: str, ip: str, user_agent: Optional[str]) -> Dict[str, Any]:
    """The first code: the secret is kept, 10 recovery codes are issued (shown
    once), and the sign-in is complete."""
    _enrolling(staff)

    def work(session, user: StaffUser, now: datetime):
        if user.must_change_password:
            return AuthError(CHANGE_PASSWORD_FIRST, 403)
        refused = _refused(user, ip, now)
        if refused is not None:
            return refused
        if not user.totp_pending_secret:
            return AuthError("Start the set-up again: no authenticator is waiting for a code.", 409)
        step = totp.verify(user.totp_pending_secret, code or "", None)
        if step is None:
            _note_failure(session, user, ip, now, "setup")
            return AuthError(INVALID_CODE, 400)
        user.totp_secret, user.totp_pending_secret = user.totp_pending_secret, None
        user.totp_last_step, user.totp_enrolled_at = step, now
        _clear_failures(user, ip)
        codes = _replace_recovery_codes(session, user, now)
        _end(session, staff.session_id, now)
        audit(session, user.hospital_id, user.id, "staff_2fa_enrolled", detail={"recovery_codes": len(codes)})
        opened = open_session(session, user, now, user_agent, SessionStage.FULL)
        return {**opened, "recovery_codes": codes}

    return _run(staff, work)


# --- re-authentication ------------------------------------------------------------------------------

def reauthenticate(staff: Staff, code: str, ip: str) -> Dict[str, Any]:
    """A fresh code for sensitive actions (a recovery code does not do here)."""
    if staff.stage != SessionStage.FULL:
        raise AuthError("Finish signing in first.", 403)

    def work(session, user: StaffUser, now: datetime):
        if not user.totp_secret:
            return AuthError("Set up two-step verification first.", 409)
        refused = _refused(user, ip, now)
        if refused is not None:
            return refused
        step = totp.verify(user.totp_secret, code or "", user.totp_last_step)
        if step is None:
            _note_failure(session, user, ip, now, "reauth")
            return AuthError(INVALID_CODE, 400)
        user.totp_last_step = step
        _clear_failures(user, ip)
        session.execute(update(StaffSession).where(StaffSession.id == staff.session_id).values(reauth_at=now))
        audit(session, user.hospital_id, user.id, "staff_reauthenticated")
        return {"fresh_until": (now + timedelta(minutes=REAUTH_MINUTES)).isoformat()}

    return _run(staff, work)


def require_fresh(staff: Staff) -> Staff:
    """403 unless this session gave a code within REAUTH_MINUTES."""
    if staff.reauth_at is None or staff.reauth_at + timedelta(minutes=REAUTH_MINUTES) <= utcnow():
        raise HTTPException(status_code=403, detail=REAUTH_REQUIRED)
    return staff


# --- resets -------------------------------------------------------------------------------------------

def reset(session, user: StaffUser) -> None:
    """Forget the authenticator and recovery codes; end every session (the
    next sign-in sets up a new authenticator)."""
    user.totp_secret = user.totp_pending_secret = None
    user.totp_last_step = user.totp_enrolled_at = None
    user.code_failures, user.code_last_failed_at, user.code_backoff_until = 0, None, None
    session.execute(delete(StaffRecoveryCode).where(StaffRecoveryCode.user_id == user.id))
    revoke_all_sessions(session, user.id)


def end_hospital_sessions(session, hospital_id: str) -> int:
    """Every live session of the hospital's staff (on approval: two-step verification starts)."""
    staff_ids = select(StaffUser.id).where(StaffUser.hospital_id == hospital_id)
    return session.execute(update(StaffSession).where(
        StaffSession.user_id.in_(staff_ids), StaffSession.revoked_at.is_(None)).values(revoked_at=utcnow())).rowcount \
        or 0
