"""User persistence — email/university-id lookups, enable/disable."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.repositories.base import Database


class UserRepository:
    COLLECTION = "users"

    def __init__(self, db: Database):
        self._db = db

    # -- writes -----------------------------------------------------------

    def create(self, user_id: str, data: Dict[str, Any]) -> None:
        self._db.collection(self.COLLECTION).document(user_id).set(data)

    def set(self, user_id: str, data: Dict[str, Any]) -> None:
        self._db.collection(self.COLLECTION).document(user_id).set(data)

    def update(self, user_id: str, data: Dict[str, Any]) -> None:
        self._db.collection(self.COLLECTION).document(user_id).update(data)

    # -- reads ------------------------------------------------------------

    def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        snap = self._db.collection(self.COLLECTION).document(user_id).get()
        if not snap.exists:
            return None
        return _with_id(snap, user_id)

    def find_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        for snap in self._db.collection(self.COLLECTION).where("email", "==", email.lower()).stream():
            data = _with_id(snap, snap.id)
            if data:
                return data
        return None

    def find_by_uid(self, uid: str) -> Optional[Dict[str, Any]]:
        for snap in self._db.collection(self.COLLECTION).where("uid", "==", uid).stream():
            data = _with_id(snap, snap.id)
            if data:
                return data
        return None

    def list_all(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for snap in self._db.collection(self.COLLECTION).order_by("created_at", "DESC").stream():
            data = _with_id(snap, snap.id)
            if data:
                results.append(data)
        return results

    def search(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        query = query.strip().lower()
        results: List[Dict[str, Any]] = []
        if not query:
            return self.list_all()[:limit]
        for user in self.list_all():
            haystack = " ".join(
                str(value).lower()
                for value in (user.get("full_name"), user.get("email"), user.get("uid"), user.get("user_id"))
                if value is not None
            )
            if query in haystack:
                results.append(user)
                if len(results) >= limit:
                    break
        return results


def _with_id(snapshot, doc_id: str) -> Optional[Dict[str, Any]]:
    if not getattr(snapshot, "exists", True):
        return None
    data = snapshot.to_dict() or {}
    if not data.get("id"):
        data["id"] = doc_id
    return data