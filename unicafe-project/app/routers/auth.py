"""Authentication routes — register and login."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_auth_service, get_current_user
from app.models.schemas import TokenResponse, UserLogin, UserPublic, UserRegister
from app.services.auth import AuthError, AuthService
from app.services.utils import ServiceError

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _raise_auth_error(exc: AuthError) -> None:
    """Map :class:`AuthError` to an :class:`HTTPException`."""

    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/register", response_model=TokenResponse)
def register(
    payload: UserRegister,
    auth: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    try:
        return auth.register(payload)
    except AuthError as exc:
        _raise_auth_error(exc)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: UserLogin,
    auth: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    try:
        return auth.login(payload)
    except AuthError as exc:
        _raise_auth_error(exc)


@router.get("/me", response_model=UserPublic)
def me(current_user: dict = Depends(get_current_user)) -> UserPublic:
    return UserPublic(
        id=str(current_user.get("id", "")),
        email=str(current_user.get("email", "")),
        full_name=str(current_user.get("full_name", "")),
        university_id=current_user.get("uid") or current_user.get("university_id"),
        is_admin=bool(current_user.get("is_admin")),
        is_active=bool(current_user.get("is_active", True)),
        created_at=str(current_user.get("created_at", "")),
    )
