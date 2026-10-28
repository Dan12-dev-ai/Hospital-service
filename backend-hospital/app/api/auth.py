"""`/auth`: staff sign-in (password, then a code from the authenticator app,
app/twofactor.py), setting up the authenticator, re-authentication,
sign-out, the current staff member, password change."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import auth, twofactor
from app.api.onboarding import client_address
from app.db import session_scope
from app.models import Hospital, SessionStage, StaffUser

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class CodeStep(BaseModel):
    #: The 6-digit code from the authenticator app, or a recovery code instead.
    code: Optional[str] = Field(default=None, max_length=12)
    recovery_code: Optional[str] = Field(default=None, max_length=40)


class Code(BaseModel):
    code: str = Field(min_length=1, max_length=12)


def _http(exc: auth.AuthError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/login")
def login(body: LoginRequest, request: Request) -> Dict[str, Any]:
    """The password. ``stage`` says what follows: ``full`` (signed in), ``totp``
    (a code is next: POST /auth/totp) or ``enroll`` (set up the authenticator)."""
    try:
        return auth.login(body.email, body.password, auth.client_user_agent(request))
    except auth.AuthError as exc:
        raise _http(exc) from exc


@router.post("/totp")
def code_step(body: CodeStep, request: Request, staff: auth.Staff = Depends(auth.session_staff)) -> Dict[str, Any]:
    """The code (or a recovery code) after the password: a new, full session."""
    if not body.code and not body.recovery_code:
        raise HTTPException(status_code=400, detail="Enter the code from your authenticator app.")
    try:
        return twofactor.complete_sign_in(staff, body.code, body.recovery_code, client_address(request),
                                          auth.client_user_agent(request))
    except auth.AuthError as exc:
        raise _http(exc) from exc


@router.post("/enroll/start")
def enroll_start(staff: auth.Staff = Depends(auth.session_staff)) -> Dict[str, Any]:
    try:
        return twofactor.enrolment_start(staff)
    except auth.AuthError as exc:
        raise _http(exc) from exc


@router.post("/enroll/confirm")
def enroll_confirm(body: Code, request: Request, staff: auth.Staff = Depends(auth.session_staff)) -> Dict[str, Any]:
    """The first code: signed in, with 10 recovery codes (shown only now)."""
    try:
        return twofactor.enrolment_confirm(staff, body.code, client_address(request), auth.client_user_agent(request))
    except auth.AuthError as exc:
        raise _http(exc) from exc


@router.post("/reauth")
def reauth(body: Code, request: Request, staff: auth.Staff = Depends(auth.current_staff)) -> Dict[str, Any]:
    """A fresh code for sensitive actions, good for 10 minutes in this session."""
    try:
        return twofactor.reauthenticate(staff, body.code, client_address(request))
    except auth.AuthError as exc:
        raise _http(exc) from exc


@router.post("/logout")
def logout(staff: auth.Staff = Depends(auth.session_staff)) -> Dict[str, bool]:
    auth.logout(staff)
    return {"ok": True}


@router.get("/me")
def me(staff: auth.Staff = Depends(auth.session_staff)) -> Dict[str, Any]:
    with session_scope(staff.hospital_id) as session:
        user = session.get(StaffUser, staff.id)
        payload = auth.staff_payload(user, session.get(Hospital, user.hospital_id))
        payload["stage"] = staff.stage
        if staff.stage == SessionStage.FULL and user.totp_secret:
            payload["recovery_codes_left"] = twofactor.recovery_codes_left(session, user.id)
        return payload


@router.post("/password")
def change_password(body: PasswordChange, staff: auth.Staff = Depends(auth.session_staff)) -> Dict[str, bool]:
    """Also the way out of a temporary password (before setting up the authenticator)."""
    if staff.stage == SessionStage.TOTP:
        raise HTTPException(status_code=403, detail=auth.INCOMPLETE)
    try:
        auth.change_password(staff, body.current_password, body.new_password)
    except auth.AuthError as exc:
        raise _http(exc) from exc
    return {"ok": True}
