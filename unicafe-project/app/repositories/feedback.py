"""Feedback persistence (post-completion surveys)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.repositories.base import Database


class FeedbackRepository:
    COLLECTION = "feedback"

    def __init__(self, db: Database):
        self._db = db

    def create(self, feedback_id: str, data: Dict[str, Any]) -> None:
        self._db.collection(self.COLLECTION).document(feedback_id).set(data)

    def get(self, feedback_id: str) -> Optional[Dict[str, Any]]:
        snap = self._db.collection(self.COLLECTION).document(feedback_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        if not data.get("id"):
            data["id"] = feedback_id
        return data

    def list_all(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for snap in (
            self._db.collection(self.COLLECTION)
            .order_by("created_at", "DESC")
            .stream()
        ):
            data = snap.to_dict() or {}
            if not data.get("id"):
                data["id"] = snap.id
            results.append(data)
        return results

    def find_for_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        for snap in (
            self._db.collection(self.COLLECTION)
            .where("order_id", "==", order_id)
            .limit(1)
            .stream()
        ):
            data = snap.to_dict() or {}
            if not data.get("id"):
                data["id"] = snap.id
            return data
        return None