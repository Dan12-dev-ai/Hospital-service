"""`/auth`: staff sign-in, sign-out, the current staff member, password change."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import auth
from app.db import session_scope
from app.models import Hospital, StaffUser

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


@router.post("/login")
def login(body: LoginRequest, request: Request) -> Dict[str, Any]:
    try:
        return auth.login(body.email, body.password, auth.client_user_agent(request))
    except auth.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/logout")
def logout(staff: auth.Staff = Depends(auth.signed_in_staff)) -> Dict[str, bool]:
    auth.logout(staff)
    return {"ok": True}


@router.get("/me")
def me(staff: auth.Staff = Depends(auth.signed_in_staff)) -> Dict[str, Any]:
    with session_scope(staff.hospital_id) as session:
        user = session.get(StaffUser, staff.id)
        return auth.staff_payload(user, session.get(Hospital, user.hospital_id))


@router.post("/password")
def change_password(body: PasswordChange, staff: auth.Staff = Depends(auth.signed_in_staff)) -> Dict[str, bool]:
    """Also the way out of a temporary password."""
    try:
        auth.change_password(staff, body.current_password, body.new_password)
    except auth.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok": True}
