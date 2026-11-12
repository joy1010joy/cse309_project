"""AI service — graceful Gemini wrapper with safe fallbacks."""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from app.config import Settings
from app.models.schemas import (
    AIRecommendationItem,
    AIRecommendationResponse,
    AIChatAction,
    AIResponse,
)
from app.repositories.menu import MenuRepository
from app.repositories.orders import OrderRepository

logger = logging.getLogger(__name__)

CHAT_SYSTEM_PROMPT = (
    "You are UniCafe's helpful campus dining assistant in Bangladesh. "
    "Use only the supplied current menu and user context. Recommend only items "
    "marked available with positive stock, always include their exact BDT price, "
    "and never invent menu items, prices, or availability. Answer directly and "
    "conversationally. For food recommendations, normally use 2–5 short sentences "
    "and recommend at most 3 items. Do not repeat the full menu or write a long "
    "explanation unless the user specifically asks for it. Use plain text without "
    "Markdown headings, bold markers, or tables."
)

CHAT_FALLBACK = (
    "I'm temporarily unavailable, but you can still choose from the available "
    "items shown on today's menu."
)

_QUANTITY_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


@dataclass
class ChatSessionState:
    """Small, user-isolated conversation state for deterministic follow-ups."""

    last_referenced_menu_item_id: Optional[str] = None
    last_referenced_item_name: Optional[str] = None
    recent_messages: List[Dict[str, str]] = field(default_factory=list)
    touched_at: float = field(default_factory=time.monotonic)


class ChatSessionStore:
    """Bounded in-process chat context keyed by authenticated user and browser tab."""

    def __init__(self, max_sessions: int = 1000, ttl_seconds: int = 7200):
        self._sessions: Dict[tuple[str, str], ChatSessionState] = {}
        self._max_sessions = max_sessions
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()

    def get(self, user_id: str, session_id: Optional[str]) -> ChatSessionState:
        key = (user_id, session_id or "default")
        now = time.monotonic()
        with self._lock:
            stale = [
                candidate
                for candidate, state in self._sessions.items()
                if now - state.touched_at > self._ttl_seconds
            ]
            for candidate in stale:
                self._sessions.pop(candidate, None)
            if key not in self._sessions and len(self._sessions) >= self._max_sessions:
                oldest = min(self._sessions, key=lambda candidate: self._sessions[candidate].touched_at)
                self._sessions.pop(oldest, None)
            state = self._sessions.setdefault(key, ChatSessionState())
            state.touched_at = now
            return state

    def record(
        self,
        state: ChatSessionState,
        prompt: str,
        response: str,
        item: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            if item:
                state.last_referenced_menu_item_id = str(item.get("id") or "") or None
                state.last_referenced_item_name = str(item.get("name") or "") or None
            state.recent_messages.extend(
                [
                    {"role": "user", "text": prompt[:500]},
                    {"role": "assistant", "text": response[:800]},
                ]
            )
            state.recent_messages = state.recent_messages[-6:]
            state.touched_at = time.monotonic()


_CHAT_SESSIONS = ChatSessionStore()


def _build_fallback_recommendations(menu_items: List[Dict[str, Any]]) -> List[AIRecommendationItem]:
    items: List[AIRecommendationItem] = []
    for item in menu_items:
        if not item.get("is_available", True) or int(item.get("stock_quantity") or 0) <= 0:
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

    def chat(
        self,
        prompt: str,
        viewer: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> AIResponse:
        items = self._menu.list_all()
        state = self._chat_state(viewer, session_id)
        local_result = self._local_chat_response(prompt, items, state)
        if local_result:
            local, referenced_item = local_result
            self._record_chat(state, prompt, local.response, referenced_item)
            return local
        context = self._build_chat_context(items, viewer, state)
        text = self._call_chat_gemini(prompt, context)
        if text:
            response = self._plain_chat_text(text)
            self._record_chat(state, prompt, response)
            return AIResponse(response=response, fallback=False, source="gemini")
        response = self._chat_fallback(prompt, items)
        self._record_chat(state, prompt, response)
        return AIResponse(
            response=response,
            fallback=True,
            source="local",
        )

    def chat_stream(
        self,
        prompt: str,
        viewer: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Yield Gemini chat chunks and a final fallback status."""

        items = self._menu.list_all()
        state = self._chat_state(viewer, session_id)
        local_result = self._local_chat_response(prompt, items, state)
        if local_result:
            local, referenced_item = local_result
            self._record_chat(state, prompt, local.response, referenced_item)
            yield {"event": "chunk", "text": local.response}
            done: Dict[str, Any] = {
                "event": "done",
                "fallback": False,
                "source": "local",
            }
            if local.action:
                done["action"] = local.action.model_dump()
            yield done
            return

        context = self._build_chat_context(items, viewer, state)
        api_key = (self._settings.gemini_api_key or "").strip()
        if not api_key:
            response = self._chat_fallback(prompt, items)
            self._record_chat(state, prompt, response)
            yield {"event": "chunk", "text": response}
            yield {"event": "done", "fallback": True, "source": "local"}
            return

        emitted = False
        failed = False
        response_parts: List[str] = []
        stream_events: queue.Queue[tuple[str, Any]] = queue.Queue()
        stopped = threading.Event()

        def read_gemini_stream() -> None:
            try:
                for text in self._iter_chat_gemini(prompt, context):
                    if stopped.is_set():
                        break
                    stream_events.put(("chunk", text))
            except Exception as exc:  # pragma: no cover - depends on remote service
                if not stopped.is_set():
                    stream_events.put(("error", exc))
            finally:
                if not stopped.is_set():
                    stream_events.put(("done", None))

        worker = threading.Thread(
            target=read_gemini_stream,
            name="unicafe-gemini-chat",
            daemon=True,
        )
        started_at = time.monotonic()
        first_deadline = started_at + self._settings.ai_chat_first_chunk_timeout_seconds
        total_deadline = started_at + self._settings.ai_chat_total_timeout_seconds
        worker.start()
        try:
            while True:
                deadline = total_deadline if emitted else first_deadline
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    failed = True
                    timeout_name = "total" if emitted else "first chunk"
                    logger.warning("Gemini chat %s deadline exceeded", timeout_name)
                    break
                try:
                    event, payload = stream_events.get(timeout=remaining)
                except queue.Empty:
                    failed = True
                    timeout_name = "total" if emitted else "first chunk"
                    logger.warning("Gemini chat %s deadline exceeded", timeout_name)
                    break
                if event == "chunk":
                    text = self._plain_chat_text(str(payload or ""))
                    if not text:
                        continue
                    emitted = True
                    response_parts.append(text)
                    yield {"event": "chunk", "text": text}
                    continue
                if event == "error":
                    failed = True
                    logger.warning("Gemini chat stream failed: %s", payload)
                break
        except GeneratorExit:
            raise
        finally:
            stopped.set()

        if emitted:
            self._record_chat(state, prompt, "".join(response_parts))
            yield {"event": "done", "fallback": failed, "source": "gemini"}
            return

        response = self._chat_fallback(prompt, items)
        self._record_chat(state, prompt, response)
        yield {"event": "chunk", "text": response}
        yield {"event": "done", "fallback": True, "source": "local"}

    # -- recommendations --------------------------------------------------

    def recommend(self, viewer: Optional[Dict[str, Any]] = None) -> AIRecommendationResponse:
        items = [
            item
            for item in self._menu.list_all()
            if item.get("is_available", True)
            and int(item.get("stock_quantity") or 0) > 0
        ]
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
                "You are UniCafe's business analyst. Use only the supplied real order, "
                "menu, inventory, and report metrics. Provide concise insights on "
                "sales, fulfilment, inventory, and customer demand. Express money in "
                "Bangladeshi Taka (৳) and never invent figures."
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

    @staticmethod
    def _chat_state(
        viewer: Optional[Dict[str, Any]],
        session_id: Optional[str],
    ) -> ChatSessionState:
        user_id = str((viewer or {}).get("id") or "anonymous")
        return _CHAT_SESSIONS.get(user_id, session_id)

    @staticmethod
    def _record_chat(
        state: ChatSessionState,
        prompt: str,
        response: str,
        item: Optional[Dict[str, Any]] = None,
    ) -> None:
        _CHAT_SESSIONS.record(state, prompt, response, item)

    @staticmethod
    def _normalise_chat_text(value: str) -> str:
        return re.sub(r"[^a-z0-9৳]+", " ", value.casefold()).strip()

    @classmethod
    def _find_menu_item(
        cls,
        prompt: str,
        items: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        normalised_prompt = f" {cls._normalise_chat_text(prompt)} "
        candidates = sorted(items, key=lambda item: len(str(item.get("name") or "")), reverse=True)
        for item in candidates:
            name = cls._normalise_chat_text(str(item.get("name") or ""))
            if name and f" {name} " in normalised_prompt:
                return item
        return None

    @staticmethod
    def _available(item: Dict[str, Any]) -> bool:
        return bool(item.get("is_available", True)) and int(item.get("stock_quantity") or 0) > 0

    @staticmethod
    def _price(item: Dict[str, Any]) -> str:
        return f"৳{float(item.get('price') or 0):g}"

    @classmethod
    def _requested_quantity(cls, prompt: str) -> Optional[int]:
        normalised = cls._normalise_chat_text(prompt)
        digit = re.search(r"\b(\d{1,3})\b", normalised)
        if digit:
            return int(digit.group(1))
        words = normalised.split()
        return next((_QUANTITY_WORDS[word] for word in words if word in _QUANTITY_WORDS), None)

    @classmethod
    def _local_chat_response(
        cls,
        prompt: str,
        items: List[Dict[str, Any]],
        state: ChatSessionState,
    ) -> Optional[tuple[AIResponse, Optional[Dict[str, Any]]]]:
        """Resolve safe deterministic requests before any Gemini client is created."""

        normalised = cls._normalise_chat_text(prompt)
        item = cls._find_menu_item(prompt, items)
        available_items = [candidate for candidate in items if cls._available(candidate)]

        asks_availability = bool(item) and any(
            phrase in normalised for phrase in ("available", "in stock", "do you have")
        )
        if asks_availability and item:
            if cls._available(item):
                response = f"Yes. {item.get('name')} is available for {cls._price(item)}."
            else:
                response = f"No. {item.get('name')} is currently unavailable."
            return AIResponse(response=response, fallback=False, source="local"), item

        asks_price = bool(item) and any(
            phrase in normalised for phrase in ("how much", "price", "cost")
        )
        if asks_price and item:
            availability = "available" if cls._available(item) else "currently unavailable"
            response = f"{item.get('name')} costs {cls._price(item)} and is {availability}."
            return AIResponse(response=response, fallback=False, source="local"), item

        if "cheapest" in normalised:
            if not available_items:
                response = "There are no available items in stock right now."
                return AIResponse(response=response, fallback=False, source="local"), None
            cheapest = min(available_items, key=lambda candidate: float(candidate.get("price") or 0))
            response = f"The cheapest available item is {cheapest.get('name')} for {cls._price(cheapest)}."
            return AIResponse(response=response, fallback=False, source="local"), cheapest

        availability_listing = (
            "what is available" in normalised
            or "what s available" in normalised
            or "show available" in normalised
            or "list available" in normalised
        )
        if availability_listing:
            if not available_items:
                response = "There are no available items in stock right now."
            else:
                labels = [f"{candidate.get('name')} ({cls._price(candidate)})" for candidate in available_items]
                response = "Available now: " + ", ".join(labels) + "."
            return AIResponse(response=response, fallback=False, source="local"), None

        price_limit = re.search(
            r"\b(?:under|below|less than)\s*(?:৳\s*)?(?:tk\s*)?(?:taka\s*)?(?:bdt\s*)?(\d+(?:\.\d+)?)",
            normalised,
        )
        subjective = any(
            phrase in normalised
            for phrase in ("light", "coffee", "filling", "goes well", "pair", "recommend", "suggest")
        )
        filter_request = any(word in normalised.split() for word in ("show", "list", "items", "options", "something"))
        if price_limit and filter_request and not subjective:
            limit = float(price_limit.group(1))
            matches = [
                candidate
                for candidate in available_items
                if float(candidate.get("price") or 0) < limit
            ]
            if not matches:
                response = f"There are no available items under ৳{limit:g} right now."
            else:
                labels = [f"{candidate.get('name')} ({cls._price(candidate)})" for candidate in matches]
                response = f"Available under ৳{limit:g}: " + ", ".join(labels) + "."
            return AIResponse(response=response, fallback=False, source="local"), None

        quantity = cls._requested_quantity(prompt)
        order_words = any(
            phrase in normalised
            for phrase in ("add", "order", "take", "give me", "i want one", "i want this", "i want it")
        )
        explicit_quantity_request = item is not None and quantity is not None and not asks_price
        followup_order = item is None and order_words
        if item is not None and (order_words or explicit_quantity_request) or followup_order:
            if item is None and state.last_referenced_menu_item_id:
                item = next(
                    (
                        candidate
                        for candidate in items
                        if str(candidate.get("id")) == state.last_referenced_menu_item_id
                    ),
                    None,
                )
            if item is None:
                response = "Which menu item would you like to add to your cart?"
                return AIResponse(response=response, fallback=False, source="local"), None
            if not cls._available(item):
                response = f"{item.get('name')} is currently unavailable, so I cannot add it to your cart."
                return AIResponse(response=response, fallback=False, source="local"), item
            requested = quantity or 1
            stock = int(item.get("stock_quantity") or 0)
            if requested > stock:
                response = f"Only {stock} {item.get('name')} are available. Please choose a quantity up to {stock}."
                return AIResponse(response=response, fallback=False, source="local"), item
            action = AIChatAction(
                type="add_to_cart",
                menu_item_id=str(item.get("id") or ""),
                quantity=requested,
            )
            unit = str(item.get("name"))
            response = f"Sure! I can add {requested} {unit} ({cls._price(item)} each) to your cart."
            return AIResponse(
                response=response,
                fallback=False,
                source="local",
                action=action,
            ), item

        return None

    @staticmethod
    def _plain_chat_text(value: str) -> str:
        """Keep chat text safe and plain while retaining SSE chunking."""

        return value.replace("*", "").replace("#", "")

    def _build_chat_context(
        self,
        items: List[Dict[str, Any]],
        viewer: Optional[Dict[str, Any]],
        state: Optional[ChatSessionState] = None,
    ) -> Dict[str, Any]:
        context: Dict[str, Any] = {
            "menu": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "category": item.get("category"),
                    "price_bdt": item.get("price"),
                    "available": bool(item.get("is_available", True)),
                    "stock": int(item.get("stock_quantity") or 0),
                }
                for item in items[:30]
            ]
        }
        if not viewer:
            return context

        context["user"] = {"name": viewer.get("full_name")}
        recent_orders = [
            order
            for order in self._orders.list_for_user(viewer["id"])
            if order.get("status") != "cancelled"
        ][:3]
        context["recent_orders"] = [
            {
                "status": order.get("status"),
                "items": [
                    {
                        "name": item.get("name"),
                        "quantity": item.get("quantity"),
                    }
                    for item in order.get("items", [])[:5]
                ],
            }
            for order in recent_orders
        ]
        if state and state.recent_messages:
            context["recent_chat"] = list(state.recent_messages[-6:])
        return context

    @staticmethod
    def _chat_prompt(prompt: str, context: Dict[str, Any]) -> str:
        return (
            f"Current context:\n{json.dumps(context, ensure_ascii=False, default=str)}\n\n"
            f"Student: {prompt}"
        )

    @staticmethod
    def _chat_generation_config(types: Any) -> Any:
        return types.GenerateContentConfig(
            system_instruction=CHAT_SYSTEM_PROMPT,
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MINIMAL,
            ),
            max_output_tokens=320,
            temperature=0.4,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True,
            ),
        )

    def _call_chat_gemini(
        self,
        prompt: str,
        context: Dict[str, Any],
    ) -> Optional[str]:
        api_key = (self._settings.gemini_api_key or "").strip()
        if not api_key:
            return None
        try:
            from google import genai  # type: ignore
            from google.genai import types  # type: ignore

            with genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    timeout=int(self._settings.ai_chat_total_timeout_seconds * 1000),
                ),
            ) as client:
                response = client.models.generate_content(
                    model=self._settings.gemini_model,
                    contents=self._chat_prompt(prompt, context),
                    config=self._chat_generation_config(types),
                )
            return getattr(response, "text", None) or None
        except Exception as exc:  # pragma: no cover - depends on remote service
            logger.warning("Gemini chat request failed: %s", exc)
            return None

    def _iter_chat_gemini(
        self,
        prompt: str,
        context: Dict[str, Any],
    ) -> Iterator[str]:
        """Yield provider chunks with the HTTP request capped by the total deadline."""

        from google import genai  # type: ignore
        from google.genai import types  # type: ignore

        with genai.Client(
            api_key=(self._settings.gemini_api_key or "").strip(),
            http_options=types.HttpOptions(
                timeout=int(self._settings.ai_chat_total_timeout_seconds * 1000),
            ),
        ) as client:
            for response in client.models.generate_content_stream(
                model=self._settings.gemini_model,
                contents=self._chat_prompt(prompt, context),
                config=self._chat_generation_config(types),
            ):
                text = getattr(response, "text", "") or ""
                if text:
                    yield text

    @classmethod
    def _chat_fallback(cls, prompt: str, items: List[Dict[str, Any]]) -> str:
        available = [
            item
            for item in items
            if item.get("is_available", True)
            and int(item.get("stock_quantity") or 0) > 0
        ]
        if not available:
            return CHAT_FALLBACK
        normalised = cls._normalise_chat_text(prompt)
        price_match = re.search(
            r"\b(?:under|below|less than)\s*(?:৳\s*)?(?:tk\s*)?(?:taka\s*)?(?:bdt\s*)?(\d+(?:\.\d+)?)",
            normalised,
        )
        price_limit = float(price_match.group(1)) if price_match else None
        coffee = [
            item
            for item in available
            if "coffee" in str(item.get("category") or "").casefold()
            or any(
                word in str(item.get("name") or "").casefold()
                for word in ("coffee", "latte", "americano", "cappuccino")
            )
        ]
        light = [
            item
            for item in available
            if str(item.get("category") or "").casefold() in {"bakery", "snack", "dessert"}
            or any(
                word in str(item.get("name") or "").casefold()
                for word in ("muffin", "croissant", "toast")
            )
        ]
        if "coffee" in normalised and "light" in normalised:
            pair = next(
                (
                    (drink, snack)
                    for drink in coffee
                    for snack in light
                    if drink.get("id") != snack.get("id")
                    and (
                        price_limit is None
                        or float(drink.get("price") or 0) + float(snack.get("price") or 0) < price_limit
                    )
                ),
                None,
            )
            if pair:
                drink, snack = pair
                total = float(drink.get("price") or 0) + float(snack.get("price") or 0)
                return (
                    f"Try {drink.get('name')} ({cls._price(drink)}) with "
                    f"{snack.get('name')} ({cls._price(snack)}); together they are ৳{total:g}."
                )

        choices = available
        if price_limit is not None:
            choices = [item for item in choices if float(item.get("price") or 0) < price_limit]
        if "coffee" in normalised and coffee:
            coffee_ids = {str(item.get("id")) for item in coffee}
            choices = [item for item in choices if str(item.get("id")) in coffee_ids]
        choices = choices[:3]
        if not choices:
            if price_limit is not None:
                return f"There are no available items under ৳{price_limit:g} right now."
            return CHAT_FALLBACK
        labels = [
            f"{item.get('name')} ({cls._price(item)})"
            for item in choices
        ]
        if len(labels) == 1:
            options = labels[0]
        elif len(labels) == 2:
            options = " or ".join(labels)
        else:
            options = ", ".join(labels[:-1]) + f", or {labels[-1]}"
        return f"You could try {options}."

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
            revenue = 0.0
            item_quantities: Dict[str, int] = {}
            for order in orders:
                if order.get("status") == "cancelled":
                    continue
                status = order.get("status", "pending")
                totals[status] = totals.get(status, 0) + 1
                revenue += float(order.get("total_amount") or 0)
                for order_item in order.get("items", []):
                    name = str(order_item.get("name") or "Unknown item")
                    item_quantities[name] = item_quantities.get(name, 0) + int(
                        order_item.get("quantity") or 0
                    )
            context["orders_summary"] = totals
            context["orders_total"] = len(orders)
            context["report_metrics"] = {
                "non_cancelled_revenue_bdt": round(revenue, 2),
                "average_order_value_bdt": round(
                    revenue / max(1, sum(totals.values())), 2
                ),
                "top_items_by_quantity": sorted(
                    item_quantities.items(),
                    key=lambda row: row[1],
                    reverse=True,
                )[:5],
            }
            context["inventory_summary"] = {
                "out_of_stock": [
                    item.get("name")
                    for item in items
                    if int(item.get("stock_quantity") or 0) == 0
                ],
                "low_stock": [
                    {
                        "name": item.get("name"),
                        "stock_quantity": int(item.get("stock_quantity") or 0),
                    }
                    for item in items
                    if 0 < int(item.get("stock_quantity") or 0) <= 5
                ],
            }
        return context

    def _call_gemini(self, system_prompt: str, user_prompt: str, context: Dict[str, Any]) -> Optional[str]:
        api_key = (self._settings.gemini_api_key or "").strip()
        if not api_key:
            logger.debug("Gemini API key missing; using fallback response")
            return None
        try:
            from google import genai  # type: ignore
            from google.genai import types  # type: ignore

            client = genai.Client(api_key=api_key)
            prompt = (
                f"Context:\n{json.dumps(context, default=str)[:12000]}\n\n"
                f"User question: {user_prompt}"
            )
            response = client.models.generate_content(
                model=self._settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                ),
            )
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
            from google import genai  # type: ignore
            from google.genai import types  # type: ignore

            client = genai.Client(api_key=api_key)
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
                "up to 3 JSON objects with keys: menu_item_id and reason. Use only ids "
                "from the provided list and never recommend zero-stock items.\n\n"
                f"Menu: {json.dumps(slim_menu, default=str)}\n\n"
                f"Recent history: {json.dumps(history[:10], default=str)}"
            )
            response = client.models.generate_content(
                model=self._settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            text = getattr(response, "text", "") or ""
            raw = json.loads(text)
            if not isinstance(raw, list):
                return None
            parsed: List[AIRecommendationItem] = []
            menu_by_id = {str(i.get("id")): i for i in items}
            for row in raw:
                if not isinstance(row, dict):
                    continue
                item_id = str(row.get("menu_item_id") or "")
                source = menu_by_id.get(item_id)
                if not source:
                    continue
                parsed.append(
                    AIRecommendationItem(
                        menu_item_id=item_id,
                        name=str(source.get("name") or ""),
                        reason=str(row.get("reason") or ""),
                        price=float(source.get("price") or 0),
                        category=str(source.get("category") or ""),
                    )
                )
                if len(parsed) >= 3:
                    break
            return parsed or None
        except Exception as exc:  # pragma: no cover
            logger.warning("Gemini recommender failed: %s", exc)
            return None
