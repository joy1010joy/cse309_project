"""Dashboard/analytics — admin KPIs."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from app.repositories.feedback import FeedbackRepository
from app.repositories.menu import MenuRepository
from app.repositories.orders import OrderRepository
from app.repositories.users import UserRepository


class DashboardService:
    def __init__(
        self,
        orders: OrderRepository,
        menu: MenuRepository,
        users: UserRepository,
        feedback: FeedbackRepository,
    ):
        self._orders = orders
        self._menu = menu
        self._users = users
        self._feedback = feedback

    def stats(self) -> Dict[str, Any]:
        orders = self._orders.list_all()
        total = len(orders)
        status_counter = Counter(order.get("status", "pending") for order in orders)
        revenue = sum(
            float(order.get("total_amount") or order.get("total") or 0.0)
            for order in orders
            if order.get("status") not in {"cancelled"}
        )
        feedback_records = self._feedback.list_all()
        avg_rating = 0.0
        if feedback_records:
            ratings = [int(f.get("rating", 0)) for f in feedback_records]
            avg_rating = round(sum(ratings) / len(ratings), 2)

        item_sales: Dict[str, int] = {}
        for order in orders:
            if order.get("status") == "cancelled":
                continue
            for item in order.get("items", []):
                key = item.get("menu_item_id") or item.get("name", "unknown")
                item_sales[key] = item_sales.get(key, 0) + int(item.get("quantity", 0))
        top_items = sorted(item_sales.items(), key=lambda kv: kv[1], reverse=True)[:5]
        top_items_payload: List[Dict[str, Any]] = []
        for menu_item_id, quantity in top_items:
            sample = next(
                (item for order in orders for item in order.get("items", []) if (item.get("menu_item_id") or item.get("name")) == menu_item_id),
                None,
            )
            top_items_payload.append({
                "menu_item_id": menu_item_id,
                "name": (sample or {}).get("name", menu_item_id),
                "quantity": quantity,
            })

        return {
            "total_orders": total,
            "orders_by_status": dict(status_counter),
            "total_revenue": round(revenue, 2),
            "total_users": len(self._users.list_all()),
            "menu_item_count": len(self._menu.list_all(include_unavailable=True)),
            "average_rating": avg_rating,
            "feedback_count": len(feedback_records),
            "top_items": top_items_payload,
        }