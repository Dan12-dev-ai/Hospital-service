"""Staff sign-in: sessions, the current staff member, and role checks."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Dict, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select, update

from app.config import get_settings
from app.db import ensure_aware, session_scope, utcnow
from app.models import AuditEvent, Hospital, StaffSession, StaffUser
from app.security import hash_password, new_session_token, password_problem, token_hash, verify_password

INVALID_LOGIN = "Incorrect email or password."


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Staff:
    """The signed-in staff member, as every route sees them."""

    id: str
    hospital_id: str
    session_id: str
    email: str
    full_name: str
    role: str
    must_change_password: bool


def audit(session, hospital_id: str, actor_id: Optional[str], action: str,
          target_type: Optional[str] = None, target_id: Optional[str] = None,
          detail: Optional[Dict[str, Any]] = None) -> None:
    session.add(AuditEvent(
        hospital_id=hospital_id, actor_id=actor_id, action=action, target_type=target_type,
        target_id=target_id, detail=json.dumps(detail) if detail else None,
    ))


def staff_payload(user: StaffUser, hospital: Optional[Hospital] = None) -> Dict[str, Any]:
    payload = {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "full_name_am": user.full_name_am,
        "role": user.role,
        "department_id": user.department_id,
        "phone": user.phone,
        "active": user.active,
        "must_change_password": user.must_change_password,
        "last_login_at": ensure_aware(user.last_login_at).isoformat() if user.last_login_at else None,
    }
    if hospital is not None:
        payload["hospital"] = {"id": hospital.id, "code": hospital.code, "name": hospital.name, "name_am": hospital.name_am}
    return payload


#: Checked against for unknown emails, so they cost the same one scrypt run
#: as a real account with a wrong password.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def _record_failure(session, user: StaffUser, now, settings) -> bool:
    """Count a failed password for ``user`` (row already locked); True if this locked it.

    Failures older than the lockout window are forgotten, so occasional typos
    over months never add up to a lockout.
    """
    window = timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
    if user.last_failed_at is None or ensure_aware(user.last_failed_at) < now - window:
        user.failed_logins = 0
    user.failed_logins += 1
    user.last_failed_at = now
    if user.failed_logins >= settings.LOGIN_LOCKOUT_ATTEMPTS:
        user.locked_until = now + window
        user.failed_logins = 0
        audit(session, user.hospital_id, user.id, "staff_locked_out")
        return True
    return False


def _locked_user(session, email: str) -> Optional[StaffUser]:
    """The account row, locked for this transaction so parallel attempts
    cannot lose failure counts (no-op on SQLite, which serialises writers)."""
    return session.scalar(select(StaffUser).where(StaffUser.email == email.strip().lower()).with_for_update())


def login(email: str, password: str, user_agent: Optional[str] = None) -> Dict[str, Any]:
    """Check the password and open a session. Raises AuthError.

    Unknown email, wrong password and locked account all answer the same,
    with the same work, so the response never tells whether an account exists.
    """
    settings = get_settings()
    now = utcnow()
    # A failed attempt is recorded and committed *before* the error is raised:
    # raising inside the transaction would roll the count (and the lockout) back.
    failure: Optional[AuthError] = None
    with session_scope() as session:
        user = _locked_user(session, email)
        if user is None:
            verify_password(password, _DUMMY_HASH)
            failure = AuthError(INVALID_LOGIN)
        else:
            correct = verify_password(password, user.password_hash)
            if user.locked_until and ensure_aware(user.locked_until) > now:
                failure = AuthError(INVALID_LOGIN)
            elif not correct:
                _record_failure(session, user, now, settings)
                failure = AuthError(INVALID_LOGIN)
            elif not user.active:
                failure = AuthError("This account has been deactivated.", status.HTTP_403_FORBIDDEN)
        if failure is None:
            return _open_session(session, user, now, settings, user_agent)
    raise failure


def _open_session(session, user: StaffUser, now, settings, user_agent: Optional[str]) -> Dict[str, Any]:
    token = new_session_token()
    expires = now + timedelta(seconds=settings.SESSION_TTL_SECONDS)
    session.add(StaffSession(token_hash=token_hash(token), user_id=user.id, expires_at=expires,
                             user_agent=(user_agent or "")[:200] or None))
    user.failed_logins = 0
    user.last_failed_at = None
    user.locked_until = None
    user.last_login_at = now
    audit(session, user.hospital_id, user.id, "staff_signed_in")
    hospital = session.get(Hospital, user.hospital_id)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": settings.SESSION_TTL_SECONDS,
        "staff": staff_payload(user, hospital),
    }


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, value = authorization.strip().partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def resolve_session(token: str) -> Staff:
    now = utcnow()
    with session_scope() as session:
        row = session.execute(
            select(StaffSession, StaffUser)
            .join(StaffUser, StaffUser.id == StaffSession.user_id)
            .where(StaffSession.token_hash == token_hash(token))
        ).first()
        if row is None:
            raise AuthError("Authentication required.")
        sess, user = row
        if sess.revoked_at is not None or ensure_aware(sess.expires_at) <= now:
            raise AuthError("Your session has ended. Please sign in again.")
        if not user.active:
            raise AuthError("This account has been deactivated.", status.HTTP_403_FORBIDDEN)
        return Staff(
            id=user.id, hospital_id=user.hospital_id, session_id=sess.id, email=user.email,
            full_name=user.full_name, role=user.role, must_change_password=user.must_change_password,
        )


def signed_in_staff(authorization: Optional[str] = Header(default=None)) -> Staff:
    """Any signed-in staff member, even one who still has to change a temporary password."""
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        return resolve_session(token)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def current_staff(staff: Staff = Depends(signed_in_staff)) -> Staff:
    """A signed-in staff member cleared to use the portal."""
    if staff.must_change_password:
        raise HTTPException(status_code=403, detail="Change your temporary password to continue.")
    return staff


def require_roles(*roles: str) -> Callable[..., Staff]:
    allowed = set(roles)

    def dependency(staff: Staff = Depends(current_staff)) -> Staff:
        if staff.role not in allowed:
            raise HTTPException(status_code=403, detail="You do not have access to this.")
        return staff

    return dependency


def logout(staff: Staff) -> None:
    with session_scope() as session:
        session.execute(
            update(StaffSession).where(StaffSession.id == staff.session_id, StaffSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        audit(session, staff.hospital_id, staff.id, "staff_signed_out")


def change_password(staff: Staff, current: str, new: str) -> None:
    """Change the password and end every other session of this account."""
    problem = password_problem(new)
    if problem:
        raise AuthError(problem, status.HTTP_400_BAD_REQUEST)
    settings = get_settings()
    now = utcnow()
    failure: Optional[AuthError] = None
    with session_scope() as session:
        user = session.scalar(select(StaffUser).where(StaffUser.id == staff.id).with_for_update())
        if user is None:
            raise AuthError("Authentication required.")
        if not verify_password(current, user.password_hash):
            # Counted like a failed sign-in: a stolen session cannot guess the
            # password without limit. Reaching the limit ends every session.
            # 400, not 401: a typo here must not look like a lost session.
            if _record_failure(session, user, now, settings):
                revoke_all_sessions(session, user.id)
            failure = AuthError("Current password is incorrect.", status.HTTP_400_BAD_REQUEST)
        elif current == new:
            failure = AuthError("Choose a password different from the current one.", status.HTTP_400_BAD_REQUEST)
        else:
            user.password_hash = hash_password(new)
            user.must_change_password = False
            user.failed_logins = 0
            session.execute(
                update(StaffSession)
                .where(StaffSession.user_id == user.id, StaffSession.id != staff.session_id,
                       StaffSession.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )
            audit(session, user.hospital_id, user.id, "staff_password_changed")
    # Raised after the commit, so a recorded failure is kept.
    if failure is not None:
        raise failure


def revoke_all_sessions(session, user_id: str) -> None:
    session.execute(
        update(StaffSession).where(StaffSession.user_id == user_id, StaffSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def client_user_agent(request: Request) -> Optional[str]:
    return request.headers.get("user-agent")
