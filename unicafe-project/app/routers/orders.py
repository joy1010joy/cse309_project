"""Order management — user-facing and admin endpoints."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import (
    get_admin_user,
    get_current_user,
    get_order_service,
)
from app.models.schemas import (
    OrderCreate,
    OrderResponse,
    OrderStatusUpdate,
)
from app.services.orders import OrderService
from app.services.utils import ServiceError

user_router = APIRouter(prefix="/api/orders", tags=["orders"])
admin_router = APIRouter(prefix="/api/admin/orders", tags=["admin"])


def _raise(exc: ServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@user_router.post("", response_model=OrderResponse, status_code=201)
def create_order(
    payload: OrderCreate,
    current_user: dict = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    try:
        return service.create(current_user, payload)
    except ServiceError as exc:
        _raise(exc)


@user_router.get("/history", response_model=List[OrderResponse])
def order_history(
    current_user: dict = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
) -> List[OrderResponse]:
    try:
        return service.list_for_user(current_user)
    except ServiceError as exc:
        _raise(exc)


@user_router.put("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(
    order_id: str,
    current_user: dict = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    try:
        return service.cancel_by_user(order_id, current_user)
    except ServiceError as exc:
        _raise(exc)


@user_router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: str,
    current_user: dict = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    try:
        order = service.get(order_id)
    except ServiceError as exc:
        _raise(exc)
    if order.user_id != current_user["id"] and not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="not authorized to view this order")
    return order


@admin_router.get("", response_model=List[OrderResponse])
def admin_list(
    _admin: dict = Depends(get_admin_user),
    service: OrderService = Depends(get_order_service),
) -> List[OrderResponse]:
    return service.list_all()


@admin_router.put("/{order_id}/status", response_model=OrderResponse)
def admin_update_status(
    order_id: str,
    payload: OrderStatusUpdate,
    actor: dict = Depends(get_admin_user),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    try:
        return service.update_status(order_id, payload, actor)
    except ServiceError as exc:
        _raise(exc)
