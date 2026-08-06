"""Inventory router — admin stock view + manual adjustments."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import get_admin_user, get_inventory_service
from app.services.inventory import InventoryService
from app.services.utils import ServiceError


router = APIRouter(prefix="/api/admin/inventory", tags=["inventory"])


def _raise(exc: ServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


class StockUpdate(BaseModel):
    stock_quantity: int = Field(ge=0)


@router.get("")
def list_stock(
    _admin: dict = Depends(get_admin_user),
    service: InventoryService = Depends(get_inventory_service),
) -> List[dict]:
    return service.list_stock()


@router.get("/{item_id}")
def get_stock(
    item_id: str,
    _admin: dict = Depends(get_admin_user),
    service: InventoryService = Depends(get_inventory_service),
) -> dict:
    try:
        return service.get_stock(item_id)
    except ServiceError as exc:
        _raise(exc)


@router.put("/{item_id}")
def update_stock(
    item_id: str,
    payload: StockUpdate,
    _admin: dict = Depends(get_admin_user),
    service: InventoryService = Depends(get_inventory_service),
) -> dict:
    try:
        return service.set_stock(item_id, payload.stock_quantity)
    except ServiceError as exc:
        _raise(exc)