"""Cross-service serializers and small helpers."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.models.schemas import OrderItemSnapshot, OrderResponse, OrderStatus


def order_to_response(order: Dict[str, Any]) -> OrderResponse:
    """Shape a raw order document into the API response model."""
    try:
        status = OrderStatus(order.get("status", "pending"))
    except ValueError:
        status = OrderStatus.PENDING
    items = [
        OrderItemSnapshot(
            menu_item_id=i.get("menu_item_id", ""),
            name=i.get("name", ""),
            quantity=int(i.get("quantity", 0)),
            price=float(i.get("price", 0)),
            subtotal=float(i.get("subtotal", 0)),
        )
        for i in order.get("items", [])
    ]
    return OrderResponse(
        id=order.get("id", ""),
        user_id=order.get("user_id", ""),
        user_email=order.get("user_email"),
        user_name=order.get("user_name"),
        status=status,
        subtotal=float(order.get("subtotal") or order.get("total_amount") or 0),
        total_amount=float(order.get("total_amount") or order.get("subtotal") or 0),
        pickup_time=_iso_or_none(order.get("pickup_time")),
        created_at=order.get("created_at") or "",
        updated_at=_iso_or_none(order.get("updated_at")),
        confirmed_at=_iso_or_none(order.get("confirmed_at")),
        ready_at=_iso_or_none(order.get("ready_at")),
        completed_at=_iso_or_none(order.get("completed_at")),
        cancelled_at=_iso_or_none(order.get("cancelled_at")),
        items=items,
        feedback_id=order.get("feedback_id"),
        stock_restored=bool(order.get("stock_restored", False)),
    )


def _iso_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
