"""Order service — create, list, status transitions, feedback hooks."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.config import Settings
from app.models.schemas import (
    ALLOWED_TRANSITIONS,
    OrderCreate,
    OrderItemSnapshot,
    OrderResponse,
    OrderStatus,
    OrderStatusUpdate,
)
from app.repositories.base import Database
from app.repositories.inventory import InventoryRepository, StockError
from app.repositories.menu import MenuRepository
from app.repositories.orders import OrderRepository
from app.repositories.users import UserRepository
from app.services.notifications import NotificationService
from app.services.utils import ServiceError
from app.utils.timezone import ensure_aware, to_iso, utcnow


class OrderService:
    STATUS_MESSAGES = {
        OrderStatus.PENDING: "Your order has been placed and is awaiting confirmation.",
        OrderStatus.CONFIRMED: "Your order has been confirmed by the kitchen.",
        OrderStatus.PREPARING: "Our team is preparing your order.",
        OrderStatus.READY: "Your order is ready for pickup!",
        OrderStatus.COMPLETED: "Order completed — thanks! You can leave feedback now.",
        OrderStatus.CANCELLED: "Your order has been cancelled.",
    }

    def __init__(
        self,
        db: Database,
        settings: Settings,
        orders: Optional[OrderRepository] = None,
        menu: Optional[MenuRepository] = None,
        inventory: Optional[InventoryRepository] = None,
        users: Optional[UserRepository] = None,
        notifications: Optional[NotificationService] = None,
    ):
        self._db = db
        self._settings = settings
        self._orders = orders or OrderRepository(db)
        self._menu = menu or MenuRepository(db)
        self._inventory = inventory or InventoryRepository(db)
        self._users = users or UserRepository(db)
        self._notifications = notifications

    # -- inventory helpers ------------------------------------------------

    def _lookup_menu(self, menu_item_id: str) -> Dict[str, Any]:
        item = self._menu.get(menu_item_id)
        if not item:
            raise ServiceError(f"menu item {menu_item_id!r} not found", 404)
        return item

    # -- creation ---------------------------------------------------------

    def create(self, user: Dict[str, Any], payload: OrderCreate) -> OrderResponse:
        if not payload.items:
            raise ServiceError("order must contain at least one item", 400)

        if payload.pickup_time is not None:
            pickup = ensure_aware(payload.pickup_time)
            if pickup < utcnow():
                raise ServiceError("pickup_time cannot be in the past", 400)

        snapshots: List[Dict[str, Any]] = []
        total = 0.0

        for entry in payload.items:
            menu_item = self._lookup_menu(entry.menu_item_id)
            if not menu_item.get("is_available", True):
                raise ServiceError(
                    f"menu item {menu_item.get('name')!r} is unavailable", 400
                )
            qty = int(entry.quantity)
            stock = int(menu_item.get("stock_quantity") or 0)
            if stock < qty:
                raise ServiceError(
                    f"insufficient stock for {menu_item.get('name')!r} "
                    f"(requested {qty}, available {stock})",
                    400,
                )
            unit_price = float(menu_item["price"])
            subtotal = round(unit_price * qty, 2)
            total += subtotal
            snapshots.append(
                {
                    "menu_item_id": menu_item["id"],
                    "name": menu_item.get("name", ""),
                    "quantity": qty,
                    "price": unit_price,
                    "subtotal": subtotal,
                }
            )

        order_id = f"order_{uuid.uuid4().hex[:16]}"
        now_iso = to_iso(utcnow())
        order_doc: Dict[str, Any] = {
            "id": order_id,
            "user_id": user["id"],
            "user_email": user.get("email"),
            "user_name": user.get("full_name"),
            "status": OrderStatus.PENDING.value,
            "items": snapshots,
            "subtotal": round(total, 2),
            "total_amount": round(total, 2),
            "pickup_time": (
                to_iso(ensure_aware(payload.pickup_time))
                if payload.pickup_time
                else None
            ),
            "created_at": now_iso,
            "updated_at": now_iso,
            "confirmed_at": None,
            "ready_at": None,
            "completed_at": None,
            "cancelled_at": None,
            "stock_restored": False,
            "feedback_id": None,
        }

        # Atomic order creation: deduct all stocks and write the order
        # document inside one Firestore transaction so there are no partial
        # deductions or rollback races.
        try:
            def _create_order_txn(txn):
                for snap in snapshots:
                    self._inventory.deduct_stock_in_txn(
                        txn, snap["menu_item_id"], int(snap["quantity"])
                    )
                self._orders.set_in_transaction(txn, order_id, order_doc)

            self._db.run_in_transaction(_create_order_txn)
        except StockError as exc:
            raise ServiceError(exc.message, exc.status_code) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise ServiceError(f"could not create order: {exc}", 500) from exc

        if self._notifications is not None:
            self._notifications.create_for_user(
                user_id=user["id"],
                type_name="order_placed",
                title=f"Order #{order_id[-6:]} placed",
                message=self.STATUS_MESSAGES[OrderStatus.PENDING],
                order_id=order_id,
                dedupe_key=f"{order_id}:pending",
            )

        return self._to_response(order_doc)

    # -- listing ----------------------------------------------------------

    def list_for_user(self, user: Dict[str, Any]) -> List[OrderResponse]:
        return [self._to_response(o) for o in self._orders.list_for_user(user["id"])]

    def list_all(self) -> List[OrderResponse]:
        return [self._to_response(o) for o in self._orders.list_all()]

    def get(self, order_id: str) -> OrderResponse:
        order = self._orders.get(order_id)
        if not order:
            raise ServiceError("order not found", 404)
        return self._to_response(order)

    # -- status updates ---------------------------------------------------

    def update_status(
        self,
        order_id: str,
        payload: OrderStatusUpdate,
        actor: Dict[str, Any],
    ) -> OrderResponse:
        order = self._orders.get(order_id)
        if not order:
            raise ServiceError("order not found", 404)

        try:
            current = OrderStatus(order.get("status", "pending"))
            target = payload.status
        except ValueError as exc:
            raise ServiceError(f"invalid status: {exc}", 400) from exc

        if target not in ALLOWED_TRANSITIONS.get(current, set()):
            raise ServiceError(
                f"cannot transition from {current.value} to {target.value}", 400
            )

        now_iso = to_iso(utcnow())
        update_data: Dict[str, Any] = {
            "status": target.value,
            "updated_at": now_iso,
        }
        if target is OrderStatus.CONFIRMED:
            update_data["confirmed_at"] = now_iso
        elif target is OrderStatus.READY:
            update_data["ready_at"] = now_iso
        elif target is OrderStatus.COMPLETED:
            update_data["completed_at"] = now_iso
        elif target is OrderStatus.CANCELLED:
            update_data["cancelled_at"] = now_iso

        if target is OrderStatus.CANCELLED and not order.get("stock_restored", False):
            for item in order.get("items", []):
                self._inventory.restore_stock(
                    item["menu_item_id"], int(item.get("quantity", 0))
                )
            update_data["stock_restored"] = True

        self._orders.update(order_id, update_data)
        order.update(update_data)

        if self._notifications is not None:
            message = self.STATUS_MESSAGES.get(target)
            if message:
                owner_id = order.get("user_id")
                if owner_id:
                    notif_type = f"order_{target.value}"
                    self._notifications.create_for_user(
                        user_id=owner_id,
                        type_name=notif_type,
                        title=f"Order #{order_id[-6:]} {target.value}",
                        message=message,
                        order_id=order_id,
                        dedupe_key=f"{order_id}:{target.value}",
                    )
                    if target is OrderStatus.COMPLETED:
                        self._notifications.create_for_user(
                            user_id=owner_id,
                            type_name="feedback_request",
                            title="Share your feedback",
                            message="Tell us how your order was today.",
                            order_id=order_id,
                            dedupe_key=f"{order_id}:feedback_request",
                        )

        return self._to_response(order)

    def cancel_by_user(self, order_id: str, user: Dict[str, Any]) -> OrderResponse:
        order = self._orders.get(order_id)
        if not order:
            raise ServiceError("order not found", 404)
        if order.get("user_id") != user["id"]:
            raise ServiceError("you can only cancel your own orders", 403)
        try:
            current = OrderStatus(order.get("status", "pending"))
        except ValueError as exc:
            raise ServiceError("invalid stored status", 500) from exc
        if OrderStatus.CANCELLED not in ALLOWED_TRANSITIONS.get(current, set()):
            raise ServiceError(
                f"order cannot be cancelled from {current.value} state", 400
            )
        return self.update_status(
            order_id, OrderStatusUpdate(status=OrderStatus.CANCELLED), user
        )

    # -- response shaping -------------------------------------------------

    def _to_response(self, order: Dict[str, Any]) -> OrderResponse:
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
            created_at=order.get("created_at") or to_iso(utcnow()),
            updated_at=_iso_or_none(order.get("updated_at")),
            confirmed_at=_iso_or_none(order.get("confirmed_at")),
            ready_at=_iso_or_none(order.get("ready_at")),
            completed_at=_iso_or_none(order.get("completed_at")),
            cancelled_at=_iso_or_none(order.get("cancelled_at")),
            items=items,
            feedback_id=order.get("feedback_id"),
            stock_restored=bool(order.get("stock_restored", False)),
        )

    def attach_feedback_id(self, order_id: str, feedback_id: str) -> None:
        self._orders.update(order_id, {"feedback_id": feedback_id})


def _iso_or_none(value: Any) -> Optional[str]:
    """Convert a datetime or ISO string to an ISO string, else ``None``."""

    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)