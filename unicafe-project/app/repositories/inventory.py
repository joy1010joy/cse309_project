"""Inventory persistence — menu items live alongside their stock fields."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.repositories.base import Database


class InventoryRepository:
    COLLECTION = "menu_items"

    def __init__(self, db: Database):
        self._db = db

    # -- reads ------------------------------------------------------------

    def get(self, menu_item_id: str) -> Optional[Dict[str, Any]]:
        snap = self._db.collection(self.COLLECTION).document(menu_item_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        if not data.get("id"):
            data["id"] = menu_item_id
        return data

    def list_all(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for snap in self._db.collection(self.COLLECTION).stream():
            data = snap.to_dict() or {}
            if not data.get("id"):
                data["id"] = snap.id
            results.append(data)
        return results

    # -- writes -----------------------------------------------------------

    def set_stock(self, menu_item_id: str, stock: int) -> None:
        if stock < 0:
            stock = 0
        is_available = stock > 0
        self._db.collection(self.COLLECTION).document(menu_item_id).update(
            {"stock_quantity": int(stock), "is_available": bool(is_available)}
        )

    def set_availability(self, menu_item_id: str, is_available: bool) -> None:
        self._db.collection(self.COLLECTION).document(menu_item_id).update(
            {"is_available": bool(is_available)}
        )

    # -- atomic stock mutation -------------------------------------------

    def deduct_stock_atomic(self, menu_item_id: str, quantity: int) -> int:
        """Atomically subtract ``quantity`` from stock via a Firestore
        transaction when available, otherwise fall back to a read-modify-write
        (sufficient for the in-memory fake used in tests)."""

        if quantity <= 0:
            raise _StockError("quantity must be positive", 400)

        if self._db.supports_transactions:
            txn = self._db.transaction()
            ref = self._db.collection(self.COLLECTION).document(menu_item_id)
            snap = txn.get(ref)
            data = snap.to_dict() or {}
            self._validate_for_deduction(data, menu_item_id, quantity)
            new_stock = int(data.get("stock_quantity", 0)) - int(quantity)
            update = {"stock_quantity": int(new_stock)}
            if new_stock <= 0:
                update["is_available"] = False
                new_stock = 0
            txn.update(ref, update)
            commit = getattr(txn, "commit", None)
            if callable(commit):
                commit()
            return new_stock

        # Fallback: read, validate, write.  Acceptable for the fake backend
        # used in unit tests.
        ref = self._db.collection(self.COLLECTION).document(menu_item_id)
        snap = ref.get()
        data = snap.to_dict() or {}
        self._validate_for_deduction(data, menu_item_id, quantity)
        new_stock = int(data.get("stock_quantity", 0)) - int(quantity)
        update: Dict[str, Any] = {"stock_quantity": int(new_stock)}
        if new_stock <= 0:
            update["is_available"] = False
            new_stock = 0
        ref.update(update)
        return new_stock

    def restore_stock(self, menu_item_id: str, quantity: int) -> None:
        if quantity <= 0:
            return

        if self._db.supports_transactions:
            txn = self._db.transaction()
            ref = self._db.collection(self.COLLECTION).document(menu_item_id)
            snap = txn.get(ref)
            data = snap.to_dict() or {}
            current = int(data.get("stock_quantity", 0))
            new_stock = current + int(quantity)
            update = {"stock_quantity": new_stock, "is_available": True}
            txn.update(ref, update)
            commit = getattr(txn, "commit", None)
            if callable(commit):
                commit()
            return

        ref = self._db.collection(self.COLLECTION).document(menu_item_id)
        snap = ref.get()
        data = snap.to_dict() or {}
        current = int(data.get("stock_quantity", 0))
        ref.update({"stock_quantity": current + int(quantity), "is_available": True})

    # -- internal --------------------------------------------------------

    @staticmethod
    def _validate_for_deduction(data: Dict[str, Any], menu_item_id: str, quantity: int) -> None:
        if not data:
            raise _StockError(f"menu item {menu_item_id!r} not found", 404)
        if not data.get("is_available", True):
            raise _StockError(
                f"menu item {data.get('name', menu_item_id)!r} is unavailable", 400
            )
        try:
            current = int(data.get("stock_quantity", 0))
        except (TypeError, ValueError):
            current = 0
        if quantity > current:
            raise _StockError(
                f"insufficient stock for {data.get('name', menu_item_id)!r}: "
                f"requested {quantity}, available {current}",
                400,
            )


class _StockError(Exception):
    """Raised by the inventory repo for known validation failures.

    Carries an HTTP status code so the service layer can re-raise as a
    :class:`ServiceError` without string parsing.
    """

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code