"""Order persistence with a small helper for transactional stock checks."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.repositories.base import Database
from app.repositories.inventory import _txn_get_doc


class OrderRepository:
    COLLECTION = "orders"

    def __init__(self, db: Database):
        self._db = db

    def document_ref(self, order_id: str):
        return self._db.collection(self.COLLECTION).document(order_id)

    # -- writes -----------------------------------------------------------

    def create(self, order_id: str, data: Dict[str, Any]) -> None:
        self._db.collection(self.COLLECTION).document(order_id).set(data)

    def update(self, order_id: str, data: Dict[str, Any]) -> None:
        self._db.collection(self.COLLECTION).document(order_id).update(data)

    def set_in_transaction(self, txn, order_id: str, data: Dict[str, Any]) -> None:
        ref = self.document_ref(order_id)
        txn.set(ref, data)

    def update_in_transaction(self, txn, order_id: str, data: Dict[str, Any]) -> None:
        ref = self.document_ref(order_id)
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

    def get_in_txn(self, txn, order_id: str) -> Tuple[Any, Optional[Dict[str, Any]]]:
        """Read an order document inside an externally-managed transaction."""
        ref = self.document_ref(order_id)
        snap = _txn_get_doc(txn, ref)
        if not getattr(snap, "exists", True):
            return ref, None
        data = snap.to_dict() or {}
        if not data:
            return ref, None
        if not data.get("id"):
            data["id"] = order_id
        return ref, data

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
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

        # Sort newest orders first in Python so Firestore does not require
        # a composite index for user_id + created_at.
        results.sort(
            key=lambda order: order.get("created_at") or "",
            reverse=True,
        )

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