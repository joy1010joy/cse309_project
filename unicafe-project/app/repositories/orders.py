"""Order persistence with a small helper for transactional stock checks."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.repositories.base import Database


class OrderRepository:
    COLLECTION = "orders"

    def __init__(self, db: Database):
        self._db = db

    # -- writes -----------------------------------------------------------

    def create(self, order_id: str, data: Dict[str, Any]) -> None:
        self._db.collection(self.COLLECTION).document(order_id).set(data)

    def update(self, order_id: str, data: Dict[str, Any]) -> None:
        self._db.collection(self.COLLECTION).document(order_id).update(data)

    def set_in_transaction(self, txn, order_id: str, data: Dict[str, Any]) -> None:
        ref = self._db.collection(self.COLLECTION).document(order_id)
        txn.set(ref, data)

    def update_in_transaction(self, txn, order_id: str, data: Dict[str, Any]) -> None:
        ref = self._db.collection(self.COLLECTION).document(order_id)
        txn.update(ref, data)

    # -- reads ------------------------------------------------------------

    def get(self, order_id: str) -> Optional[Dict[str, Any]]:
        snap = self._db.collection(self.COLLECTION).document(order_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        if not data.get("id"):
            data["id"] = order_id
        return data

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for snap in (
            self._db.collection(self.COLLECTION)
            .where("user_id", "==", user_id)
            .order_by("created_at", "DESC")
            .stream()
        ):
            data = snap.to_dict() or {}
            if not data.get("id"):
                data["id"] = snap.id
            results.append(data)
        return results

    def list_all(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for snap in self._db.collection(self.COLLECTION).order_by("created_at", "DESC").stream():
            data = snap.to_dict() or {}
            if not data.get("id"):
                data["id"] = snap.id
            results.append(data)
        return results

    def list_by_status(self, status: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for snap in (
            self._db.collection(self.COLLECTION)
            .where("status", "==", status)
            .order_by("created_at")
            .stream()
        ):
            data = snap.to_dict() or {}
            if not data.get("id"):
                data["id"] = snap.id
            results.append(data)
        return results

    def has_feedback(self, order_id: str) -> bool:
        snap = self._db.collection(self.COLLECTION).document(order_id).get()
        if not snap.exists:
            return False
        return bool((snap.to_dict() or {}).get("feedback_id"))

    def attach_feedback(self, order_id: str, feedback_id: str) -> None:
        """Record the feedback id on the corresponding order document."""
        self.update(order_id, {"feedback_id": feedback_id})