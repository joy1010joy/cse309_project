"""Notification service — creation, listing, mark-as-read."""
from __future__ import annotations

from typing import List, Optional

from app.config import Settings
from app.models.schemas import NotificationRecord, NotificationType
from app.repositories.notifications import NotificationRepository
from app.utils.timezone import to_iso, utcnow


class NotificationService:
    def __init__(
        self,
        notifications: NotificationRepository,
        settings: Settings,
    ):
        self._repo = notifications
        self._settings = settings

    # -- creation --------------------------------------------------------

    def create_for_user(
        self,
        user_id: str,
        type_name: NotificationType | str,
        title: str,
        message: str,
        order_id: Optional[str] = None,
        dedupe_key: Optional[str] = None,
    ) -> Optional[NotificationRecord]:
        if dedupe_key:
            existing = self._repo.find_by_dedupe(user_id, dedupe_key)
            if existing and not existing.get("is_read"):
                return None  # de-duplicate

        if isinstance(type_name, NotificationType):
            type_value = type_name.value
        else:
            type_value = NotificationType.coerce(type_name)

        notif_id = self._repo.new_id()
        record = NotificationRecord(
            id=notif_id,
            user_id=user_id,
            type=type_value,
            title=title,
            message=message,
            order_id=order_id,
            is_read=False,
            dedupe_key=dedupe_key,
            created_at=to_iso(utcnow()),
        )
        self._repo.create(notif_id, record.model_dump())
        return record

    # -- reads / mutations ------------------------------------------------

    def list_for_user(self, user_id: str, limit: int = 50) -> List[NotificationRecord]:
        results: List[NotificationRecord] = []
        for raw in self._repo.list_for_user(user_id, limit=limit):
            try:
                results.append(NotificationRecord(**raw))
            except Exception:
                continue
        return results

    def list_all(self) -> List[NotificationRecord]:
        results: List[NotificationRecord] = []
        for raw in self._repo.list_all():
            try:
                results.append(NotificationRecord(**raw))
            except Exception:
                continue
        return results

    def mark_read(self, user_id: str, notification_id: str) -> bool:
        record = self._repo.get(notification_id)
        if not record or record.get("user_id") != user_id:
            return False
        if record.get("is_read"):
            return True
        self._repo.update(
            notification_id,
            {"is_read": True, "read_at": to_iso(utcnow())},
        )
        return True

    def mark_all_read(self, user_id: str) -> int:
        count = 0
        read_at = to_iso(utcnow())
        for raw in self._repo.list_for_user(user_id, limit=200):
            if raw.get("is_read"):
                continue
            self._repo.update(raw["id"], {"is_read": True, "read_at": read_at})
            count += 1
        return count

    def unread_count(self, user_id: str) -> int:
        return self._repo.count_unread(user_id)