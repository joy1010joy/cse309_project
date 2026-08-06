"""Security helpers: password hashing and JWT token utilities."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

# ``pbkdf2_sha256`` is dependency-free and ships with passlib.  We avoid
# ``bcrypt`` 4.x quirks by using a stable KDF.  The hash format is prefixed
# with ``$pbkdf2-sha256$`` and is therefore easy to recognise in logs.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


class TokenError(Exception):
    """Raised when a JWT cannot be decoded or has invalid claims."""


def hash_password(plain: str) -> str:
    """Hash a plaintext password using the configured context."""

    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against the stored hash."""

    if not plain or not hashed:
        return False
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def create_access_token(
    subject: str,
    extra_claims: Mapping[str, Any] | None = None,
    expires_minutes: int | None = None,
) -> str:
    """Create a signed JWT for ``subject`` (typically a user id)."""

    settings = get_settings()
    expires = datetime.now(tz=timezone.utc) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload: dict[str, Any] = {"sub": subject, "exp": expires}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode ``token`` and return the payload.

    Raises :class:`TokenError` if the token is malformed, expired, or has an
    invalid signature.
    """

    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:  # pragma: no cover - exercised in tests
        raise TokenError(str(exc)) from exc