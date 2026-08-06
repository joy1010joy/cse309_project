"""Menu item persistence."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.repositories.base import Database


class MenuRepository:
    COLLECTION = "menu_items"

    def __init__(self, db: Database):
        self._db = db

    # -- writes -----------------------------------------------------------

    def create(self, item_id: str, data: Dict[str, Any]) -> None:
        # Always normalise the schema to the canonical field names.
        normalised = self._normalise(data, item_id=item_id)
        self._db.collection(self.COLLECTION).document(item_id).set(normalised)

    def update(self, item_id: str, data: Dict[str, Any]) -> None:
        normalised = self._normalise(data)
        self._db.collection(self.COLLECTION).document(item_id).update(normalised)

    def delete(self, item_id: str) -> None:
        self._db.collection(self.COLLECTION).document(item_id).delete()

    # -- reads ------------------------------------------------------------

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        snap = self._db.collection(self.COLLECTION).document(item_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        return self._normalise(data)

    def list_all(self, include_unavailable: bool = True) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for snap in self._db.collection(self.COLLECTION).order_by("category").stream():
            data = snap.to_dict() or {}
            data = self._normalise(data)
            if not include_unavailable and not data.get("is_available", True):
                continue
            results.append(data)
        return results

    def list_by_category(self, category: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for snap in (
            self._db.collection(self.COLLECTION)
            .where("category", "==", category)
            .order_by("name")
            .stream()
        ):
            data = snap.to_dict() or {}
            results.append(self._normalise(data))
        return results

    # -- schema normalisation --------------------------------------------

    @staticmethod
    def _normalise(data: Dict[str, Any], item_id: Optional[str] = None) -> Dict[str, Any]:
        out = dict(data)
        if item_id is not None:
            out["id"] = item_id
        # Map legacy ``stock`` → ``stock_quantity`` and ``available`` → ``is_available``.
        if "stock_quantity" not in out and "stock" in out:
            out["stock_quantity"] = out["stock"]
        if "is_available" not in out and "available" in out:
            out["is_available"] = out["available"]
        out.setdefault("is_available", True)
        out.setdefault("stock_quantity", 0)
        out["stock_quantity"] = int(out.get("stock_quantity") or 0)
        return out