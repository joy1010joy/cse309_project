"""Menu browsing and admin menu management."""
from __future__ import annotations

from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)

from app.dependencies import get_admin_user, get_menu_service
from app.models.schemas import (
    MenuItemCreate,
    MenuItemResponse,
    MenuItemUpdate,
)
from app.services.menu import MenuService
from app.services.utils import ServiceError


public_router = APIRouter(prefix="/api/menu", tags=["menu"])
admin_router = APIRouter(prefix="/api/admin/menu", tags=["admin"])


def _raise(exc: ServiceError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.message,
    )


def _to_response(item: dict) -> MenuItemResponse:
    return MenuItemResponse(
        id=str(item.get("id", "")),
        name=str(item.get("name", "")),
        description=str(item.get("description", "") or ""),
        price=float(item.get("price", 0.0)),
        category=str(item.get("category", "")),
        stock_quantity=int(item.get("stock_quantity", 0) or 0),
        is_available=bool(item.get("is_available", True)),
        created_at=item.get("created_at"),
        updated_at=item.get("updated_at"),
    )


@public_router.get("", response_model=List[MenuItemResponse])
def public_list(
    category: Optional[str] = Query(default=None),
    include_unavailable: bool = Query(default=False),
    service: MenuService = Depends(get_menu_service),
) -> List[MenuItemResponse]:
    items = service.list_items(
        include_unavailable=include_unavailable,
    )

    if category:
        items = [
            item
            for item in items
            if item.get("category") == category
        ]

    return [_to_response(item) for item in items]


@public_router.get(
    "/{item_id}",
    response_model=MenuItemResponse,
)
def public_get(
    item_id: str,
    service: MenuService = Depends(get_menu_service),
) -> MenuItemResponse:
    try:
        item = service.get(item_id)
    except ServiceError as exc:
        _raise(exc)

    return _to_response(item)


@admin_router.post(
    "",
    response_model=MenuItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def admin_create(
    payload: MenuItemCreate,
    _admin: dict = Depends(get_admin_user),
    service: MenuService = Depends(get_menu_service),
) -> MenuItemResponse:
    try:
        item = service.create(payload)
    except ServiceError as exc:
        _raise(exc)

    return _to_response(item)


@admin_router.put(
    "/{item_id}",
    response_model=MenuItemResponse,
)
def admin_update(
    item_id: str,
    payload: MenuItemUpdate,
    _admin: dict = Depends(get_admin_user),
    service: MenuService = Depends(get_menu_service),
) -> MenuItemResponse:
    try:
        item = service.update(item_id, payload)
    except ServiceError as exc:
        _raise(exc)

    return _to_response(item)


@admin_router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def admin_delete(
    item_id: str,
    _admin: dict = Depends(get_admin_user),
    service: MenuService = Depends(get_menu_service),
) -> Response:
    try:
        service.delete(item_id)
    except ServiceError as exc:
        _raise(exc)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
