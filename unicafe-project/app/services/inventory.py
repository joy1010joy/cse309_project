"""Inventory service — read-only admin views over stock."""
from __future__ import annotations

from typing import Any, Dict, List

from app.repositories.inventory import InventoryRepository
from app.services.utils import ServiceError


def _stock_of(item: Dict[str, Any]) -> int:
    try:
        return int(item.get("stock_quantity") or 0)
    except (TypeError, ValueError):
        return 0


class InventoryService:
    def __init__(self, inventory: InventoryRepository) -> None:
        self._inventory = inventory

    def list_stock(self) -> List[Dict[str, Any]]:
        items = self._inventory.list_all()
        items.sort(key=lambda item: item.get("name", ""))
        return [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "category": item.get("category"),
                "stock_quantity": _stock_of(item),
                "is_available": bool(item.get("is_available", True)),
            }
            for item in items
        ]

    def get_stock(self, item_id: str) -> Dict[str, Any]:
        item = self._inventory.get(item_id)
        if not item:
            raise ServiceError(f"menu item '{item_id}' not found", status_code=404)
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "stock_quantity": _stock_of(item),
            "is_available": bool(item.get("is_available", True)),
        }

    def set_stock(self, item_id: str, stock: int) -> Dict[str, Any]:
        if stock < 0:
            raise ServiceError("stock cannot be negative", status_code=400)
        item = self._inventory.get(item_id)
        if not item:
            raise ServiceError(f"menu item '{item_id}' not found", status_code=404)
        self._inventory.set_stock(item_id, stock)
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "stock_quantity": stock,
        }