"""User management — admin-only user listing, profile updates."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
import re

from app.dependencies import (
    get_admin_user,
    get_current_user,
    get_order_repository,
    get_user_repository,
    get_user_service,
)
from app.models.schemas import AdminUserStatusUpdate, AdminUserSummary, ProfileUpdate
from app.repositories.orders import OrderRepository
from app.repositories.users import UserRepository
from app.services.users import UserService
from app.services.utils import ServiceError
from app.utils.timezone import to_iso, utcnow

router = APIRouter(prefix="/api", tags=["users"])
admin_router = APIRouter(prefix="/api/admin/users", tags=["admin"])


def _raise(exc: ServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _build_summary(user: Dict[str, Any], orders: OrderRepository) -> AdminUserSummary:
    user_orders = orders.list_for_user(user.get("id", ""))
    total_spent = sum(
        float(o.get("total_amount") or 0)
        for o in user_orders
        if o.get("status") not in {"cancelled"}
    )
    return AdminUserSummary(
        id=str(user.get("id", "")),
        full_name=str(user.get("full_name", "")),
        email=str(user.get("email", "")),
        university_id=user.get("uid") or user.get("university_id"),
        is_admin=bool(user.get("is_admin")),
        is_active=bool(user.get("is_active", True)),
        created_at=str(user.get("created_at", "")),
        order_count=len(user_orders),
        total_spent=round(total_spent, 2),
    )


@router.get("/profile")
def get_profile(current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "id": current_user.get("id", ""),
        "email": current_user.get("email", ""),
        "full_name": current_user.get("full_name", ""),
        "university_id": current_user.get("uid") or current_user.get("university_id"),
        "is_admin": bool(current_user.get("is_admin")),
        "is_active": bool(current_user.get("is_active", True)),
        "created_at": current_user.get("created_at"),
    }


@router.put("/profile")
def update_profile(
    payload: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
    users: UserRepository = Depends(get_user_repository),
) -> Dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)
    new_email = updates.get("email")
    if new_email:
        existing = users.find_by_email(new_email)
        if existing and existing.get("id") != current_user["id"]:
            raise HTTPException(status_code=409, detail="email already in use")
    # Map ``university_id`` -> ``uid`` to keep the document schema stable.
    if "university_id" in updates:
        updates["uid"] = updates.pop("university_id") or None
    updates["updated_at"] = to_iso(utcnow())
    users.update(current_user["id"], updates)
    return users.get(current_user["id"]) or {}


@admin_router.get("", response_model=List[AdminUserSummary])
def admin_list_users(
    q: Optional[str] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    _admin: dict = Depends(get_admin_user),
    service: UserService = Depends(get_user_service),
    users: UserRepository = Depends(get_user_repository),
    orders: OrderRepository = Depends(get_order_repository),
) -> List[AdminUserSummary]:
    raw = service.list(q)
    if is_active is not None:
        raw = [u for u in raw if bool(u.get("is_active", True)) == is_active]
    return [_build_summary(u, orders) for u in raw]


@admin_router.get("/{user_id}", response_model=AdminUserSummary)
def admin_get_user(
    user_id: str,
    _admin: dict = Depends(get_admin_user),
    users: UserRepository = Depends(get_user_repository),
    orders: OrderRepository = Depends(get_order_repository),
) -> AdminUserSummary:
    user = users.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    return _build_summary(user, orders)


@admin_router.put("/{user_id}/status", response_model=AdminUserSummary)
def admin_set_status(
    user_id: str,
    payload: AdminUserStatusUpdate,
    actor: dict = Depends(get_admin_user),
    service: UserService = Depends(get_user_service),
    users: UserRepository = Depends(get_user_repository),
    orders: OrderRepository = Depends(get_order_repository),
) -> AdminUserSummary:
    try:
        user = service.set_status(user_id, payload.is_active, actor)
    except ServiceError as exc:
        _raise(exc)
    return _build_summary(user, orders)
