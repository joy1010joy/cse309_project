"""Notification persistence."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.repositories.base import Database


class NotificationRepository:
    COLLECTION = "notifications"

    def __init__(self, db: Database):
        self._db = db

    # -- id helpers --------------------------------------------------------

    def new_id(self) -> str:
        # Firestore document ids may be auto-generated but for testing with
        # the in-memory fake we mint a deterministic-looking string.
        return f"notif_{uuid.uuid4().hex[:16]}"

    # -- writes -----------------------------------------------------------

    def create(self, notification_id: str, data: Dict[str, Any]) -> None:
        self._db.collection(self.COLLECTION).document(notification_id).set(data)

    def update(self, notification_id: str, data: Dict[str, Any]) -> None:
        self._db.collection(self.COLLECTION).document(notification_id).update(data)

    def upsert(self, notification_id: str, data: Dict[str, Any]) -> None:
        # We use set with merge to behave like an upsert that doesn't clobber
        # the ``read`` flag if it has already been set true.
        self._db.collection(self.COLLECTION).document(notification_id).set(data, merge=True)

    # -- reads ------------------------------------------------------------

    def get(self, notification_id: str) -> Optional[Dict[str, Any]]:
        snap = self._db.collection(self.COLLECTION).document(notification_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        if not data.get("id"):
            data["id"] = notification_id
        return data

    def list_for_user(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        # Filter by user_id only, then sort/limit in Python so Firestore does
        # not require a composite index on (user_id, created_at).
        results: List[Dict[str, Any]] = []
        for snap in (
            self._db.collection(self.COLLECTION)
            .where("user_id", "==", user_id)
            .stream()
        ):
            data = snap.to_dict() or {}
            if not data.get("id"):
                data["id"] = snap.id
            results.append(data)
        results.sort(key=lambda n: n.get("created_at") or "", reverse=True)
        if limit is not None:
            results = results[:limit]
        return results

    def list_all(self, limit: int = 100) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for snap in (
            self._db.collection(self.COLLECTION)
            .order_by("created_at", "DESC")
            .limit(limit)
            .stream()
        ):
            data = snap.to_dict() or {}
            if not data.get("id"):
                data["id"] = snap.id
            results.append(data)
        return results

    def count_unread(self, user_id: str) -> int:
        return sum(
            1
            for n in self.list_for_user(user_id)
            if not n.get("is_read", False)
        )

    def find_by_dedupe(self, user_id: str, dedupe_key: str) -> Optional[Dict[str, Any]]:
        """Return the most-recent notification matching the dedupe key, if any."""
        for raw in self.list_for_user(user_id, limit=200):
            if raw.get("dedupe_key") == dedupe_key:
                return raw
        return None