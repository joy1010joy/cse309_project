"""Menu service — CRUD operations with category validation."""
from __future__ import annotations

from typing import Any, Dict, List

from app.models.schemas import MenuItemCreate, MenuItemUpdate
from app.repositories.menu import MenuRepository
from app.services.utils import ServiceError


class MenuService:
    def __init__(self, menu: MenuRepository):
        self._menu = menu

    def list_items(self, include_unavailable: bool = True) -> List[Dict[str, Any]]:
        return self._menu.list_all(include_unavailable=include_unavailable)

    def get(self, item_id: str) -> Dict[str, Any]:
        item = self._menu.get(item_id)
        if not item:
            raise ServiceError("menu item not found", 404)
        return item

    def create(self, payload: MenuItemCreate) -> Dict[str, Any]:
        item_id = payload.name.lower().replace(" ", "_")
        existing = self._menu.get(item_id)
        if existing:
            raise ServiceError("menu item with this name already exists", 409)
        doc = payload.model_dump()
        doc["id"] = item_id
        self._menu.create(item_id, doc)
        return self._menu.get(item_id)

    def update(self, item_id: str, payload: MenuItemUpdate) -> Dict[str, Any]:
        if not self._menu.get(item_id):
            raise ServiceError("menu item not found", 404)
        supplied = payload.model_dump(exclude_unset=True)
        data = {
            key: value
            for key, value in supplied.items()
            if value is not None or key == "image_url"
        }
        if not data:
            return self._menu.get(item_id)
        self._menu.update(item_id, data)
        return self._menu.get(item_id)

    def delete(self, item_id: str) -> None:
        if not self._menu.get(item_id):
            raise ServiceError("menu item not found", 404)
        self._menu.delete(item_id)
