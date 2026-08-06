"""Authentication service — registration, login, admin seeding."""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from app.config import Settings
from app.models.schemas import TokenResponse, UserLogin, UserRegister
from app.repositories.users import UserRepository
from app.utils.security import create_access_token, hash_password, verify_password
from app.utils.timezone import utcnow


class AuthError(Exception):
    """Raised for any authentication failure."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        settings: Settings,
    ):
        self._users = users
        self._settings = settings

    # -- registration ----------------------------------------------------

    def register(self, payload: UserRegister) -> TokenResponse:
        email = payload.email.lower()
        if self._users.find_by_email(email):
            raise AuthError("an account with this email already exists", 409)
        if payload.university_id and self._users.find_by_uid(payload.university_id):
            raise AuthError("university ID already registered", 409)

        now_iso = utcnow().isoformat()
        # Document id is auto-generated so users can update their email or
        # name without breaking foreign keys (e.g. orders).
        doc_id = f"user_{uuid.uuid4().hex[:16]}"
        user_data: Dict[str, Any] = {
            "id": doc_id,
            "email": email,
            "uid": payload.university_id,
            "full_name": payload.full_name,
            "password_hash": hash_password(payload.password),
            "is_admin": False,
            "is_active": True,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        self._users.create(doc_id, user_data)
        return self._build_token_response(doc_id, user_data)

    # -- login -----------------------------------------------------------

    def login(self, payload: UserLogin) -> TokenResponse:
        user = self._users.find_by_email(payload.email.lower())
        if not user:
            raise AuthError("invalid email or password", 401)
        if not user.get("is_active", True):
            raise AuthError("account disabled", 403)
        password_hash = user.get("password_hash") or ""
        if not verify_password(payload.password, password_hash):
            raise AuthError("invalid email or password", 401)
        return self._build_token_response(user["id"], user)

    # -- helpers ---------------------------------------------------------

    def seed_default_admin(self) -> bool:
        """Create the bootstrap admin if no admin exists.  Returns True if a
        new admin was created.  Safe to call repeatedly."""

        for existing in self._users.list_all():
            if existing.get("is_admin"):
                return False

        email = (self._settings.admin_email or "").strip().lower()
        admin_password = self._settings.admin_password

        if not email or not admin_password:
            return False

        if self._users.find_by_email(email):
            return False

        now_iso = utcnow().isoformat()
        admin_uid = self._settings.admin_full_name.replace(" ", "_").lower() or "admin"
        doc_id = _normalise_doc_id(admin_uid)

        admin_data = {
            "id": doc_id,
            "email": email,
            "uid": admin_uid,
            "full_name": self._settings.admin_full_name,
            "password_hash": hash_password(admin_password),
            "is_admin": True,
            "is_active": True,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        self._users.create(doc_id, admin_data)
        return True

    # ------------------------------------------------------------------

    def _build_token_response(self, user_id: str, user: Dict) -> TokenResponse:
        token = create_access_token(
            subject=user_id,
            extra_claims={
                "email": user.get("email", ""),
                "is_admin": bool(user.get("is_admin", False)),
            },
        )
        return TokenResponse(
            access_token=token,
            token_type="bearer",
            is_admin=bool(user.get("is_admin", False)),
            user_id=user_id,
        )


def _normalise_doc_id(raw: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in raw.strip().lower()) or "user"