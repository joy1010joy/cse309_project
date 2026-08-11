"""AI service — graceful Gemini wrapper with safe fallbacks."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.config import Settings
from app.models.schemas import (
    AIRecommendationItem,
    AIRecommendationResponse,
    AIResponse,
)
from app.repositories.menu import MenuRepository
from app.repositories.orders import OrderRepository

logger = logging.getLogger(__name__)


def _build_fallback_recommendations(menu_items: List[Dict[str, Any]]) -> List[AIRecommendationItem]:
    items: List[AIRecommendationItem] = []
    for item in menu_items:
        if not item.get("is_available", True):
            continue
        items.append(
            AIRecommendationItem(
                menu_item_id=str(item.get("id") or ""),
                name=str(item.get("name", "")),
                reason="Popular pick based on current availability.",
                price=float(item.get("price", 0.0)),
                category=str(item.get("category", "")),
            )
        )
        if len(items) >= 3:
            break
    return items


class AIService:
    """Thin wrapper over Gemini for chat/recommendations/admin insights.

    Any missing configuration or runtime error is caught and a safe fallback
    response is returned so the rest of the application continues to work.
    """

    def __init__(
        self,
        menu: MenuRepository,
        orders: OrderRepository,
        settings: Settings,
    ):
        self._menu = menu
        self._orders = orders
        self._settings = settings

    # -- chat -------------------------------------------------------------

    def chat(self, prompt: str, viewer: Optional[Dict[str, Any]] = None) -> AIResponse:
        items = self._menu.list_all()
        context = self._build_context(items, viewer)
        text = self._call_gemini(
            system_prompt=(
                "You are UniCafe's helpful assistant. Recommend items from the menu, "
                "explain pickup times, and answer student questions."
            ),
            user_prompt=prompt,
            context=context,
        )
        if text:
            return AIResponse(response=text, fallback=False)
        return AIResponse(
            response=(
                "I'm temporarily unavailable, but you can browse the menu and place "
                "a pre-order for pickup. Popular choices include coffee, sandwiches, "
                "and today's specials."
            ),
            fallback=True,
        )

    # -- recommendations --------------------------------------------------

    def recommend(self, viewer: Optional[Dict[str, Any]] = None) -> AIRecommendationResponse:
        items = [item for item in self._menu.list_all() if item.get("is_available", True)]
        history: List[Dict[str, Any]] = []
        if viewer:
            for order in self._orders.list_for_user(viewer["id"]):
                history.extend(order.get("items", []))
        recs = self._call_recommender(items, history)
        if recs:
            return AIRecommendationResponse(recommendations=recs, fallback=False)
        return AIRecommendationResponse(
            recommendations=_build_fallback_recommendations(items),
            fallback=True,
        )

    # -- admin insights ---------------------------------------------------

    def admin_insights(self) -> AIResponse:
        items = self._menu.list_all()
        orders = self._orders.list_all()
        context = self._build_context(items, viewer=None, orders=orders)
        text = self._call_gemini(
            system_prompt=(
                "You are UniCafe's business analyst. Provide concise insights on "
                "sales, inventory, and customer behaviour based on the data below."
            ),
            user_prompt="Summarise today's performance and suggest two actions for the manager.",
            context=context,
        )
        if text:
            return AIResponse(response=text, fallback=False)
        completed = sum(1 for o in orders if o.get("status") == "completed")
        pending = sum(1 for o in orders if o.get("status") == "pending")
        return AIResponse(
            response=(
                f"Insights temporarily unavailable. Snapshot: {len(orders)} orders, "
                f"{completed} completed, {pending} pending, {len(items)} menu items. "
                "Review low-stock inventory and clear pending orders first."
            ),
            fallback=True,
        )

    # -- helpers ----------------------------------------------------------

    def _build_context(
        self,
        items: List[Dict[str, Any]],
        viewer: Optional[Dict[str, Any]],
        orders: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        context: Dict[str, Any] = {
            "menu": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "category": item.get("category"),
                    "price": item.get("price"),
                    "available": item.get("is_available", True),
                    "stock_quantity": item.get("stock_quantity", 0),
                }
                for item in items[:50]
            ]
        }
        if viewer:
            context["viewer"] = {
                "id": viewer.get("id"),
                "name": viewer.get("full_name"),
                "is_admin": bool(viewer.get("is_admin")),
            }
        if orders is not None:
            totals: Dict[str, int] = {}
            for order in orders:
                if order.get("status") == "cancelled":
                    continue
                status = order.get("status", "pending")
                totals[status] = totals.get(status, 0) + 1
            context["orders_summary"] = totals
            context["orders_total"] = len(orders)
        return context

    def _call_gemini(self, system_prompt: str, user_prompt: str, context: Dict[str, Any]) -> Optional[str]:
        api_key = (self._settings.gemini_api_key or "").strip()
        if not api_key:
            logger.debug("Gemini API key missing; using fallback response")
            return None
        try:
            import google.generativeai as genai  # type: ignore

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name="gemini-1.5-flash")
            prompt = (
                f"{system_prompt}\n\n"
                f"Context:\n{json.dumps(context, default=str)[:2000]}\n\n"
                f"User question: {user_prompt}"
            )
            response = model.generate_content(prompt)
            return getattr(response, "text", None) or None
        except Exception as exc:  # pragma: no cover - depends on remote service
            logger.warning("Gemini request failed: %s", exc)
            return None

    def _call_recommender(
        self,
        items: List[Dict[str, Any]],
        history: List[Dict[str, Any]],
    ) -> Optional[List[AIRecommendationItem]]:
        api_key = (self._settings.gemini_api_key or "").strip()
        if not api_key:
            return None
        try:
            import google.generativeai as genai  # type: ignore

            genai.configure(api_key=api_key)
            slim_menu = [
                {
                    "id": i.get("id"),
                    "name": i.get("name"),
                    "price": i.get("price"),
                    "category": i.get("category"),
                    "stock_quantity": i.get("stock_quantity", 0),
                }
                for i in items[:50]
            ]
            prompt = (
                "You are UniCafe's recommendation engine. From the menu below, return "
                "3 JSON objects with keys: menu_item_id, name, reason, price, category. "
                "Use only ids from the provided list.\n\n"
                f"Menu: {json.dumps(slim_menu, default=str)}\n\n"
                f"Recent history: {json.dumps(history[:10], default=str)}"
            )
            model = genai.GenerativeModel(model_name="gemini-1.5-flash")
            response = model.generate_content(prompt)
            text = getattr(response, "text", "") or ""
            start = text.find("[")
            end = text.rfind("]")
            if start == -1 or end == -1:
                return None
            raw = json.loads(text[start : end + 1])
            parsed: List[AIRecommendationItem] = []
            valid_ids = {str(i.get("id")) for i in items}
            for row in raw:
                item_id = str(row.get("menu_item_id") or "")
                if item_id not in valid_ids:
                    continue
                parsed.append(
                    AIRecommendationItem(
                        menu_item_id=item_id,
                        name=str(row.get("name") or ""),
                        reason=str(row.get("reason") or ""),
                        price=float(row.get("price") or 0),
                        category=str(row.get("category") or ""),
                    )
                )
            return parsed or None
        except Exception as exc:  # pragma: no cover
            logger.warning("Gemini recommender failed: %s", exc)
            return None
