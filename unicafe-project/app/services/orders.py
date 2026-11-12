"""Order service — create, list, status transitions, feedback hooks."""
from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


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

    # -- creation ---------------------------------------------------------

    def create(self, user: Dict[str, Any], payload: OrderCreate) -> OrderResponse:
        if not payload.items:
            raise ServiceError("order must contain at least one item", 400)

        if payload.pickup_time is not None:
            pickup = ensure_aware(payload.pickup_time)
            if pickup < utcnow():
                raise ServiceError("pickup_time cannot be in the past", 400)

        order_id = f"order_{uuid.uuid4().hex[:16]}"
        now_iso = to_iso(utcnow())
        pickup_iso = (
            to_iso(ensure_aware(payload.pickup_time)) if payload.pickup_time else None
        )
        requested = [(entry.menu_item_id, int(entry.quantity)) for entry in payload.items]

        try:
            def _create_order_txn(txn):
                # 1) ALL READS first (Firestore requirement)
                reads = []
                for menu_item_id, qty in requested:
                    ref, data = self._inventory.get_in_txn(txn, menu_item_id)
                    reads.append((ref, menu_item_id, qty, data))

                # 2) Validate + build snapshots from transaction-read values
                snapshots: List[Dict[str, Any]] = []
                total = 0.0
                stock_writes = []
                for ref, menu_item_id, qty, data in reads:
                    InventoryRepository._validate_for_deduction(data, menu_item_id, qty)
                    unit_price = float(data.get("price") or 0)
                    subtotal = round(unit_price * qty, 2)
                    total += subtotal
                    new_stock = int(data.get("stock_quantity", 0)) - qty
                    stock_writes.append((ref, new_stock))
                    snapshots.append(
                        {
                            "menu_item_id": data.get("id") or menu_item_id,
                            "name": data.get("name", ""),
                            "category": data.get("category", ""),
                            "quantity": qty,
                            "price": unit_price,
                            "subtotal": subtotal,
                        }
                    )

                order_doc: Dict[str, Any] = {
                    "id": order_id,
                    "user_id": user["id"],
                    "user_email": user.get("email"),
                    "user_name": user.get("full_name"),
                    "status": OrderStatus.PENDING.value,
                    "items": snapshots,
                    "subtotal": round(total, 2),
                    "total_amount": round(total, 2),
                    "pickup_time": pickup_iso,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "confirmed_at": None,
                    "ready_at": None,
                    "completed_at": None,
                    "cancelled_at": None,
                    "stock_restored": False,
                    "feedback_id": None,
                }

                # 3) ALL WRITES after reads
                for ref, new_stock in stock_writes:
                    self._inventory.write_stock_in_txn(txn, ref, new_stock)
                self._orders.set_in_transaction(txn, order_id, order_doc)
                return order_doc

            order_doc = self._db.run_in_transaction(_create_order_txn)
        except StockError as exc:
            raise ServiceError(exc.message, exc.status_code) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise ServiceError(f"could not create order: {exc}", 500) from exc

        self._notify_safe(
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

        if target is OrderStatus.CANCELLED:
            return self._cancel_atomic(order_id, actor_user_id=None)

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

        self._orders.update(order_id, update_data)
        order.update(update_data)

        self._emit_status_notifications(order_id, order, target)
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
        return self._cancel_atomic(order_id, actor_user_id=user["id"])

    def _cancel_atomic(
        self,
        order_id: str,
        actor_user_id: Optional[str],
    ) -> OrderResponse:
        """Cancel an order and restore stock exactly once in one transaction."""

        try:
            def _cancel_txn(txn):
                order_ref, order = self._orders.get_in_txn(txn, order_id)
                if not order:
                    raise ServiceError("order not found", 404)

                if actor_user_id is not None and order.get("user_id") != actor_user_id:
                    raise ServiceError("you can only cancel your own orders", 403)

                try:
                    current = OrderStatus(order.get("status", "pending"))
                except ValueError as exc:
                    raise ServiceError("invalid stored status", 500) from exc

                if OrderStatus.CANCELLED not in ALLOWED_TRANSITIONS.get(current, set()):
                    raise ServiceError(
                        f"order cannot be cancelled from {current.value} state", 400
                    )

                # Read all menu docs before any writes when stock still needs restore.
                restores = []
                if not order.get("stock_restored", False):
                    for item in order.get("items", []):
                        menu_item_id = item.get("menu_item_id")
                        qty = int(item.get("quantity", 0))
                        if not menu_item_id or qty <= 0:
                            continue
                        ref, data = self._inventory.get_in_txn(txn, menu_item_id)
                        current_stock = int(data.get("stock_quantity", 0))
                        restores.append((ref, current_stock + qty))

                now_iso = to_iso(utcnow())
                update_data: Dict[str, Any] = {
                    "status": OrderStatus.CANCELLED.value,
                    "updated_at": now_iso,
                    "cancelled_at": now_iso,
                    "stock_restored": True,
                }

                for ref, new_stock in restores:
                    self._inventory.write_stock_in_txn(txn, ref, new_stock)

                self._orders.update_in_transaction(txn, order_id, update_data)
                order.update(update_data)
                return order

            order = self._db.run_in_transaction(_cancel_txn)
        except ServiceError:
            raise
        except StockError as exc:
            raise ServiceError(exc.message, exc.status_code) from exc
        except Exception as exc:
            raise ServiceError(f"could not cancel order: {exc}", 500) from exc

        self._emit_status_notifications(order_id, order, OrderStatus.CANCELLED)
        return self._to_response(order)

    # -- notifications (best-effort) --------------------------------------

    def _notify_safe(
        self,
        *,
        user_id: str,
        type_name: str,
        title: str,
        message: str,
        order_id: str,
        dedupe_key: str,
    ) -> None:
        if self._notifications is None:
            return
        try:
            self._notifications.create_for_user(
                user_id=user_id,
                type_name=type_name,
                title=title,
                message=message,
                order_id=order_id,
                dedupe_key=dedupe_key,
            )
        except Exception as exc:  # noqa: BLE001 — never fail committed orders
            logger.warning("notification create failed for %s: %s", dedupe_key, exc)

    def _emit_status_notifications(
        self,
        order_id: str,
        order: Dict[str, Any],
        target: OrderStatus,
    ) -> None:
        message = self.STATUS_MESSAGES.get(target)
        owner_id = order.get("user_id")
        if not message or not owner_id:
            return
        self._notify_safe(
            user_id=owner_id,
            type_name=f"order_{target.value}",
            title=f"Order #{order_id[-6:]} {target.value}",
            message=message,
            order_id=order_id,
            dedupe_key=f"{order_id}:{target.value}",
        )
        if target is OrderStatus.COMPLETED:
            self._notify_safe(
                user_id=owner_id,
                type_name="feedback_request",
                title="Share your feedback",
                message="Tell us how your order was today.",
                order_id=order_id,
                dedupe_key=f"{order_id}:feedback_request",
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
