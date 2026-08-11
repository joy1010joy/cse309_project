"""Inventory persistence — menu items live alongside their stock fields."""
from __future__ import annotations

import types
from typing import Any, Dict, List, Optional, Tuple

from app.repositories.base import Database


def _txn_get_doc(txn, ref):
    """Read a single document inside a transaction.

    Real Firestore ``txn.get(doc_ref)`` returns a generator; the in-memory
    fake returns a :class:`DocumentSnapshot` directly.  This helper
    normalises the result so callers always get one snapshot.
    """
    result = txn.get(ref)
    if isinstance(result, types.GeneratorType):
        return next(result)
    # Already a snapshot (FakeFirestore)
    return result


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

    def document_ref(self, menu_item_id: str):
        return self._db.collection(self.COLLECTION).document(menu_item_id)

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
            raise StockError("quantity must be positive", 400)

        if self._db.supports_transactions:
            ref = self.document_ref(menu_item_id)

            def _callback(txn):
                snap = _txn_get_doc(txn, ref)
                data = snap.to_dict() or {}
                self._validate_for_deduction(data, menu_item_id, quantity)
                new_stock = int(data.get("stock_quantity", 0)) - int(quantity)
                update: Dict[str, Any] = {"stock_quantity": int(new_stock)}
                if new_stock <= 0:
                    update["is_available"] = False
                    new_stock = 0
                    update["stock_quantity"] = new_stock
                txn.update(ref, update)
                return new_stock

            return self._db.run_in_transaction(_callback)

        # Fallback: read, validate, write.  Acceptable for the fake backend
        # used in unit tests.
        ref = self.document_ref(menu_item_id)
        snap = ref.get()
        data = snap.to_dict() or {}
        self._validate_for_deduction(data, menu_item_id, quantity)
        new_stock = int(data.get("stock_quantity", 0)) - int(quantity)
        update: Dict[str, Any] = {"stock_quantity": int(new_stock)}
        if new_stock <= 0:
            update["is_available"] = False
            new_stock = 0
            update["stock_quantity"] = new_stock
        ref.update(update)
        return new_stock

    def restore_stock(self, menu_item_id: str, quantity: int) -> None:
        if quantity <= 0:
            return

        if self._db.supports_transactions:
            ref = self.document_ref(menu_item_id)

            def _callback(txn):
                snap = _txn_get_doc(txn, ref)
                data = snap.to_dict() or {}
                current = int(data.get("stock_quantity", 0))
                new_stock = current + int(quantity)
                update = {"stock_quantity": new_stock, "is_available": True}
                txn.update(ref, update)

            self._db.run_in_transaction(_callback)
            return

        ref = self.document_ref(menu_item_id)
        snap = ref.get()
        data = snap.to_dict() or {}
        current = int(data.get("stock_quantity", 0))
        ref.update({"stock_quantity": current + int(quantity), "is_available": True})

    # -- transaction-aware helpers for order atomicity --------------------

    def get_in_txn(self, txn, menu_item_id: str) -> Tuple[Any, Dict[str, Any]]:
        """Read a menu item inside an externally-managed transaction."""
        ref = self.document_ref(menu_item_id)
        snap = _txn_get_doc(txn, ref)
        data = snap.to_dict() or {}
        if not data.get("id"):
            data["id"] = menu_item_id
        return ref, data

    def write_stock_in_txn(self, txn, ref, stock_quantity: int) -> None:
        """Write stock inside an externally-managed transaction (after reads)."""
        stock = max(0, int(stock_quantity))
        txn.update(
            ref,
            {
                "stock_quantity": stock,
                "is_available": stock > 0,
            },
        )

    def deduct_stock_in_txn(self, txn, menu_item_id: str, quantity: int) -> int:
        """Deduct stock within an externally-managed transaction.

        Prefer the multi-item all-reads-then-all-writes pattern in
        :class:`OrderService` for Firestore compliance.  This helper remains
        for single-item transactional updates.
        """
        if quantity <= 0:
            raise StockError("quantity must be positive", 400)

        ref, data = self.get_in_txn(txn, menu_item_id)
        self._validate_for_deduction(data, menu_item_id, quantity)
        new_stock = int(data.get("stock_quantity", 0)) - int(quantity)
        if new_stock < 0:
            new_stock = 0
        self.write_stock_in_txn(txn, ref, new_stock)
        return new_stock

    def restore_stock_in_txn(self, txn, menu_item_id: str, quantity: int) -> None:
        """Restore stock within an externally-managed transaction."""
        if quantity <= 0:
            return
        ref, data = self.get_in_txn(txn, menu_item_id)
        current = int(data.get("stock_quantity", 0))
        self.write_stock_in_txn(txn, ref, current + int(quantity))

    # -- internal --------------------------------------------------------

    @staticmethod
    def _validate_for_deduction(data: Dict[str, Any], menu_item_id: str, quantity: int) -> None:
        if not data:
            raise StockError(f"menu item {menu_item_id!r} not found", 404)
        if not data.get("is_available", True):
            raise StockError(
                f"menu item {data.get('name', menu_item_id)!r} is unavailable", 400
            )
        try:
            current = int(data.get("stock_quantity", 0))
        except (TypeError, ValueError):
            current = 0
        if quantity > current:
            raise StockError(
                f"insufficient stock for {data.get('name', menu_item_id)!r}: "
                f"requested {quantity}, available {current}",
                400,
            )


class StockError(Exception):
    """Raised by the inventory repo for known validation failures.

    Carries an HTTP status code so the service layer can re-raise as a
    :class:`ServiceError` without string parsing.
    """

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
