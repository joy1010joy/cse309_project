"""Centralized configuration loaded from environment variables.

All sensitive or environment-specific values are sourced from `.env` (via
``python-dotenv``) or the real process environment.  The settings object
exposes typed attributes and a couple of small helpers used elsewhere.
"""
from __future__ import annotations

import os
import secrets
from functools import lru_cache
from typing import List

from dotenv import load_dotenv

# Load .env if present.  ``override=False`` so real environment variables win.
load_dotenv(override=False)


def _split_origins(raw: str | None) -> List[str]:
    if not raw:
        return ["http://localhost:8000"]
    items = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return items or ["http://localhost:8000"]


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


class Settings:
    """Container for application configuration."""

    # JWT -----------------------------------------------------------------
    jwt_secret_key: str
    jwt_algorithm: str
    access_token_expire_minutes: int

    # Firebase ------------------------------------------------------------
    firebase_credentials_path: str | None
    firebase_emulator_host: str | None

    # Gemini --------------------------------------------------------------
    gemini_api_key: str | None
    gemini_model: str

    # Admin bootstrap -----------------------------------------------------
    admin_email: str | None
    admin_password: str | None
    admin_full_name: str

    # CORS ----------------------------------------------------------------
    cors_origins: List[str]

    # Misc ----------------------------------------------------------------
    project_timezone: str

    def __init__(self) -> None:
        # If no secret is configured we generate an ephemeral one.  This is
        # only safe for development; production deployments *must* set
        # ``JWT_SECRET_KEY``.  We log a warning during application startup.
        secret = os.getenv("JWT_SECRET_KEY")
        if not secret:
            secret = secrets.token_urlsafe(48)
            self._ephemeral_secret = True
        else:
            self._ephemeral_secret = False
        self.jwt_secret_key = secret

        self.jwt_algorithm = os.getenv("JWT_ALGORITHM", "HS256")
        self.access_token_expire_minutes = _int_env(
            "ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24
        )

        self.firebase_credentials_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
        self.firebase_emulator_host = os.getenv("FIRESTORE_EMULATOR_HOST")

        self.gemini_api_key = os.getenv("GEMINI_API_KEY") or None
        self.gemini_model = (
            os.getenv("GEMINI_MODEL") or "gemini-3.6-flash"
        ).strip()

        self.admin_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower() or None
        self.admin_password = os.getenv("ADMIN_PASSWORD") or None
        self.admin_full_name = os.getenv("ADMIN_FULL_NAME", "Cafe Admin")

        self.cors_origins = _split_origins(os.getenv("CORS_ORIGINS"))

        self.project_timezone = os.getenv("PROJECT_TIMEZONE", "Asia/Dhaka")

    @property
    def ephemeral_secret(self) -> bool:
        """Whether the JWT secret was auto-generated for this process."""

        return getattr(self, "_ephemeral_secret", False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""

    return Settings()


def reset_settings_cache() -> None:
    """Clear the lru_cache on :func:`get_settings` (test helper)."""

    get_settings.cache_clear()
