"""Timezone helpers.

The project is intended for Dhaka, Bangladesh.  Firestore timestamps are
stored in UTC; this module converts to the configured local timezone for
display.  Tests override :data:`PROJECT_TIMEZONE` via env var.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings

try:
    DHAKA = ZoneInfo("Asia/Dhaka")
except ZoneInfoNotFoundError:  # pragma: no cover - extremely unlikely
    DHAKA = timezone.utc


def project_zone() -> ZoneInfo:
    name = get_settings().project_timezone
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return DHAKA


def utcnow() -> datetime:
    """Return ``datetime.now(tz=timezone.utc)`` for consistency."""

    return datetime.now(tz=timezone.utc)


def to_utc(dt: datetime) -> datetime:
    """Convert ``dt`` to UTC.  Naive datetimes are assumed UTC."""

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ensure_aware(dt: datetime) -> datetime:
    """Return ``dt`` as an aware UTC datetime.  Naive datetimes are assumed
    to be in the project timezone (Dhaka) and converted accordingly."""

    if dt.tzinfo is None:
        return dt.replace(tzinfo=project_zone()).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


def to_local(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert ``dt`` to the project timezone.  Returns ``None`` unchanged."""

    if dt is None:
        return None
    return to_utc(dt).astimezone(project_zone())


def to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Return ISO formatted string in the project timezone."""

    local = to_local(dt)
    return local.isoformat() if local else None


def local_date_string(dt: datetime) -> str:
    """Return the YYYY-MM-DD representation in the project timezone."""

    return to_utc(dt).astimezone(project_zone()).date().isoformat()


def local_hour(dt: datetime) -> int:
    return to_utc(dt).astimezone(project_zone()).hour