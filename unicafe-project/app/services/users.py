"""Admin user management service."""
from __future__ import annotations

from typing import Any, Dict, List

from app.repositories.users import UserRepository
from app.services.utils import ServiceError


class UserService:
    def __init__(self, users: UserRepository):
        self._users = users

    def list(self, query: str | None = None) -> List[Dict[str, Any]]:
        if query:
            return self._users.search(query)
        return self._users.list_all()

    def set_status(self, user_id: str, is_active: bool, actor: Dict[str, Any]) -> Dict[str, Any]:
        target = self._users.get(user_id)
        if not target:
            raise ServiceError("user not found", 404)
        if target.get("is_admin") and target["id"] == actor["id"]:
            raise ServiceError("admins cannot disable their own account", 400)
        self._users.update(user_id, {"is_active": is_active})
        return self._users.get(user_id)

    def toggle_admin(self, user_id: str, is_admin: bool, actor: Dict[str, Any]) -> Dict[str, Any]:
        target = self._users.get(user_id)
        if not target:
            raise ServiceError("user not found", 404)
        # Refuse to demote the last admin.
        if not is_admin and target.get("is_admin"):
            admins = [u for u in self._users.list_all() if u.get("is_admin")]
            if len(admins) <= 1:
                raise ServiceError("cannot remove the last administrator", 400)
        self._users.update(user_id, {"is_admin": is_admin})
        return self._users.get(user_id)

    def profile(self, user: Dict[str, Any]) -> Dict[str, Any]:
        return user