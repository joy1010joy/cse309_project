"""Notification service — creation, listing, and read-state management."""
from __future__ import annotations

from typing import List, Optional, Union

from app.config import Settings
from app.models.schemas import NotificationRecord, NotificationType
from app.repositories.notifications import NotificationRepository
from app.services.utils import ServiceError
from app.utils.timezone import to_iso, utcnow


class NotificationService:
    def __init__(
        self,
        notifications: NotificationRepository,
        settings: Settings,
    ):
        self._repo = notifications
        self._settings = settings

    def create_for_user(
        self,
        user_id: str,
        type_name: Union[NotificationType, str],
        title: str,
        message: str,
        order_id: Optional[str] = None,
        dedupe_key: Optional[str] = None,
    ) -> Optional[NotificationRecord]:
        if dedupe_key:
            existing = self._repo.find_by_dedupe(
                user_id=user_id,
                dedupe_key=dedupe_key,
            )
            if existing:
                return None

        if isinstance(type_name, NotificationType):
            type_value = type_name.value
        else:
            type_value = NotificationType.coerce(type_name)

        notification_id = self._repo.new_id()

        record = NotificationRecord(
            id=notification_id,
            user_id=user_id,
            type=type_value,
            title=title,
            message=message,
            order_id=order_id,
            is_read=False,
            dedupe_key=dedupe_key,
            created_at=to_iso(utcnow()),
            read_at=None,
        )

        self._repo.create(
            notification_id=notification_id,
            data=record.model_dump(),
        )

        return record

    def list_for_user(
        self,
        user_id: str,
        limit: int = 50,
    ) -> List[NotificationRecord]:
        notifications: List[NotificationRecord] = []

        for raw in self._repo.list_for_user(
            user_id=user_id,
            limit=limit,
        ):
            try:
                notifications.append(NotificationRecord(**raw))
            except (TypeError, ValueError):
                continue

        return notifications

    def list_all(self) -> List[NotificationRecord]:
        notifications: List[NotificationRecord] = []

        for raw in self._repo.list_all():
            try:
                notifications.append(NotificationRecord(**raw))
            except (TypeError, ValueError):
                continue

        return notifications

    def mark_read(
        self,
        user_id: str,
        notification_id: str,
    ) -> NotificationRecord:
        record = self._repo.get(notification_id)

        if not record or record.get("user_id") != user_id:
            raise ServiceError(
                message="Notification not found",
                status_code=404,
            )

        if not record.get("is_read", False):
            read_at = to_iso(utcnow())

            self._repo.update(
                notification_id=notification_id,
                data={
                    "is_read": True,
                    "read_at": read_at,
                },
            )

            record["is_read"] = True
            record["read_at"] = read_at

        return NotificationRecord(**record)

    def mark_all_read(self, user_id: str) -> int:
        updated_count = 0
        read_at = to_iso(utcnow())

        for raw in self._repo.list_for_user(
            user_id=user_id,
            limit=200,
        ):
            if raw.get("is_read", False):
                continue

            notification_id = raw.get("id")
            if not notification_id:
                continue

            self._repo.update(
                notification_id=notification_id,
                data={
                    "is_read": True,
                    "read_at": read_at,
                },
            )
            updated_count += 1

        return updated_count

    def unread_count(self, user_id: str) -> int:
        return self._repo.count_unread(user_id=user_id)
