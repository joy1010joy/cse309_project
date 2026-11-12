"""Feedback service — post-completion reviews."""
from __future__ import annotations

from typing import Any, Dict, List

from app.config import Settings
from app.models.schemas import FeedbackCreate, FeedbackRecord
from app.repositories.feedback import FeedbackRepository
from app.repositories.orders import OrderRepository
from app.repositories.users import UserRepository
from app.services.utils import ServiceError
from app.utils.timezone import to_iso, utcnow


class FeedbackService:
    def __init__(
        self,
        feedback: FeedbackRepository,
        orders: OrderRepository,
        users: UserRepository,
        settings: Settings,
    ):
        self._feedback = feedback
        self._orders = orders
        self._users = users
        self._settings = settings

    def submit(self, user: Dict[str, Any], payload: FeedbackCreate) -> FeedbackRecord:
        order = self._orders.get(payload.order_id)
        if not order:
            raise ServiceError("order not found", 404)
        if order.get("user_id") != user["id"]:
            raise ServiceError("you can only review your own orders", 403)
        if order.get("status") != "completed":
            raise ServiceError("feedback can only be left on completed orders", 400)
        if self._orders.has_feedback(payload.order_id) or self._feedback.find_for_order(payload.order_id):
            raise ServiceError("feedback already submitted for this order", 409)

        feedback_id = f"fb_{payload.order_id}"
        now_iso = to_iso(utcnow())
        record = FeedbackRecord(
            id=feedback_id,
            order_id=payload.order_id,
            user_id=user["id"],
            user_name=str(user.get("full_name") or ""),
            rating=payload.rating,
            comment=payload.comment,
            created_at=now_iso,
        )
        self._feedback.create(feedback_id, record.model_dump())
        self._orders.attach_feedback(payload.order_id, feedback_id)
        return record

    def list_all(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for raw in self._feedback.list_all():
            data = dict(raw)
            user = self._users.get(data.get("user_id", ""))
            data["user_name"] = (user or {}).get("full_name", "")
            results.append(data)
        return results