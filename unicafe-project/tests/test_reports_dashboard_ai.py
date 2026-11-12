"""Reports, dashboard, and AI contract tests."""
from __future__ import annotations

import time

from app.config import get_settings
from app.services.ai import AIService
from tests.conftest import auth_header, seed_menu_item, seed_user


def _setup(client, fake_db):
    seed_user(
        fake_db,
        email="admin@uni.edu",
        password="password1",
        is_admin=True,
        user_id="admin_1",
    )
    seed_user(
        fake_db,
        email="student@uni.edu",
        password="password1",
        user_id="student_1",
    )
    seed_menu_item(
        fake_db,
        item_id="burger",
        name="Burger",
        price=200,
        stock=20,
        category="Food",
    )
    seed_menu_item(
        fake_db,
        item_id="cola",
        name="Cola",
        price=50,
        stock=20,
        category="Drinks",
    )
    admin = auth_header(client, "admin@uni.edu", "password1")
    user = auth_header(client, "student@uni.edu", "password1")
    return admin, user


def test_reports_dashboard_and_csv(client, fake_db):
    admin, user = _setup(client, fake_db)

    order = client.post(
        "/api/orders",
        headers=user,
        json={
            "items": [
                {"menu_item_id": "burger", "quantity": 2},
                {"menu_item_id": "cola", "quantity": 1},
            ]
        },
    )
    assert order.status_code == 201
    order_id = order.json()["id"]
    for status in ("confirmed", "preparing", "ready", "completed"):
        assert (
            client.put(
                f"/api/admin/orders/{order_id}/status",
                headers=admin,
                json={"status": status},
            ).status_code
            == 200
        )

    daily = client.get("/api/admin/reports/daily", headers=admin)
    assert daily.status_code == 200
    assert daily.json()["total_orders"] >= 1
    assert daily.json()["total_revenue"] >= 450

    bad_day = client.get("/api/admin/reports/daily?day=not-a-date", headers=admin)
    assert bad_day.status_code == 400

    monthly = client.get("/api/admin/reports/monthly", headers=admin)
    assert monthly.status_code == 200

    bad_month = client.get("/api/admin/reports/monthly?year_month=2024-13", headers=admin)
    assert bad_month.status_code == 400

    popular = client.get("/api/admin/reports/popular-items?limit=5", headers=admin)
    assert popular.status_code == 200
    assert popular.json()[0]["total_quantity"] >= 1

    food_only = client.get(
        "/api/admin/reports/popular-items?category=Food",
        headers=admin,
    )
    assert food_only.status_code == 200
    assert all(row["category"].lower() == "food" for row in food_only.json())

    csv_res = client.get("/api/admin/reports/export?report=daily", headers=admin)
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers.get("content-type", "")
    assert "attachment" in csv_res.headers.get("content-disposition", "")
    assert "total_orders" in csv_res.text

    dash = client.get("/api/admin/dashboard", headers=admin)
    assert dash.status_code == 200
    body = dash.json()
    assert "total_orders" in body
    assert "orders_by_status" in body
    assert "total_revenue" in body
    assert body["orders_by_status"].get("completed", 0) >= 1


def test_ai_fallback_contracts(client, fake_db):
    admin, user = _setup(client, fake_db)

    chat = client.post(
        "/api/ai/chat",
        headers=user,
        json={"message": "Suggest something filling but not too expensive."},
    )
    assert chat.status_code == 200
    body = chat.json()
    assert "response" in body
    assert body["fallback"] is True
    assert "reply" not in body

    stream = client.post(
        "/api/ai/chat/stream",
        headers=user,
        json={"message": "Suggest something filling but not too expensive."},
    )
    assert stream.status_code == 200
    assert "text/event-stream" in stream.headers["content-type"]
    assert "event: ready" in stream.text
    assert "event: chunk" in stream.text
    assert '"fallback": true' in stream.text

    recs = client.get("/api/ai/recommendations", headers=user)
    assert recs.status_code == 200
    data = recs.json()
    assert data["fallback"] is True
    assert isinstance(data["recommendations"], list)
    assert len(data["recommendations"]) >= 1
    assert "menu_item_id" in data["recommendations"][0]

    insights = client.get("/api/admin/ai/insights", headers=admin)
    assert insights.status_code == 200
    assert "response" in insights.json()
    assert insights.json()["fallback"] is True

    forbidden = client.get("/api/admin/ai/insights", headers=user)
    assert forbidden.status_code == 403


def test_chat_uses_minimal_thinking_and_short_output_cap():
    from google.genai import types

    from app.services.ai import AIService

    config = AIService._chat_generation_config(types)

    assert config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    assert config.thinking_config.thinking_budget is None
    assert config.max_output_tokens == 320
    assert config.automatic_function_calling.disable is True


def test_local_chat_intents_keep_context_and_never_call_gemini(client, fake_db, monkeypatch):
    seed_user(
        fake_db,
        email="local-chat@uni.edu",
        password="password1",
        user_id="local_chat_user",
    )
    seed_menu_item(fake_db, item_id="muffin", name="Blueberry Muffin", price=120, stock=20, category="Bakery")
    seed_menu_item(fake_db, item_id="sandwich", name="Chicken Sandwich", price=250, stock=3, category="Food")
    seed_menu_item(fake_db, item_id="latte", name="Classic Latte", price=180, stock=25, category="Coffee")
    seed_menu_item(fake_db, item_id="cappuccino", name="Cappuccino", price=190, stock=25, category="Coffee")
    seed_menu_item(fake_db, item_id="sold-out", name="Sold Out Slice", price=90, stock=0, category="Bakery")
    user = auth_header(client, "local-chat@uni.edu", "password1")

    def unexpected_gemini(*_args, **_kwargs):
        raise AssertionError("local intent called Gemini")

    monkeypatch.setattr(AIService, "_call_chat_gemini", unexpected_gemini)

    availability = client.post(
        "/api/ai/chat",
        headers=user,
        json={"message": "Is Blueberry Muffin available?", "session_id": "flow-a"},
    )
    assert availability.status_code == 200
    assert availability.json() == {
        "response": "Yes. Blueberry Muffin is available for ৳120.",
        "fallback": False,
        "source": "local",
        "action": None,
    }

    muffin_order = client.post(
        "/api/ai/chat",
        headers=user,
        json={"message": "I want to order", "session_id": "flow-a"},
    ).json()
    assert muffin_order["source"] == "local"
    assert muffin_order["action"] == {
        "type": "add_to_cart",
        "menu_item_id": "muffin",
        "quantity": 1,
    }

    price = client.post(
        "/api/ai/chat",
        headers=user,
        json={"message": "How much is Chicken Sandwich?", "session_id": "flow-b"},
    ).json()
    assert "৳250" in price["response"]
    assert price["source"] == "local"

    two_sandwiches = client.post(
        "/api/ai/chat",
        headers=user,
        json={"message": "Add two", "session_id": "flow-b"},
    ).json()
    assert two_sandwiches["action"] == {
        "type": "add_to_cart",
        "menu_item_id": "sandwich",
        "quantity": 2,
    }

    over_stock = client.post(
        "/api/ai/chat",
        headers=user,
        json={"message": "Give me 5", "session_id": "flow-b"},
    ).json()
    assert over_stock["source"] == "local"
    assert over_stock["action"] is None
    assert "Only 3 Chicken Sandwich" in over_stock["response"]

    filtered = client.post(
        "/api/ai/chat",
        headers=user,
        json={"message": "Show me something under ৳200", "session_id": "flow-c"},
    ).json()
    assert filtered["source"] == "local"
    assert all(name in filtered["response"] for name in ("Blueberry Muffin", "Classic Latte", "Cappuccino"))
    assert "Chicken Sandwich" not in filtered["response"]
    assert "Sold Out Slice" not in filtered["response"]

    cheapest = client.post(
        "/api/ai/chat",
        headers=user,
        json={"message": "What is the cheapest item?", "session_id": "flow-c"},
    ).json()
    assert "Blueberry Muffin" in cheapest["response"]
    assert "৳120" in cheapest["response"]

    isolated = client.post(
        "/api/ai/chat",
        headers=user,
        json={"message": "I want to order", "session_id": "different-tab"},
    ).json()
    assert isolated["source"] == "local"
    assert isolated["action"] is None
    assert "Which menu item" in isolated["response"]

    explicit = client.post(
        "/api/ai/chat",
        headers=user,
        json={"message": "Give me 2 Blueberry Muffin", "session_id": "explicit-item"},
    ).json()
    assert explicit["action"] == {
        "type": "add_to_cart",
        "menu_item_id": "muffin",
        "quantity": 2,
    }


def test_local_stream_survives_provider_unavailable_and_returns_action(client, fake_db):
    seed_user(
        fake_db,
        email="offline-chat@uni.edu",
        password="password1",
        user_id="offline_chat_user",
    )
    seed_menu_item(fake_db, item_id="latte", name="Classic Latte", price=180, stock=25, category="Coffee")
    user = auth_header(client, "offline-chat@uni.edu", "password1")

    availability = client.post(
        "/api/ai/chat/stream",
        headers=user,
        json={"message": "Is Classic Latte available?", "session_id": "offline-flow"},
    )
    assert availability.status_code == 200
    assert "Yes. Classic Latte is available for ৳180." in availability.text
    assert '"source": "local"' in availability.text
    assert '"fallback": false' in availability.text

    order = client.post(
        "/api/ai/chat/stream",
        headers=user,
        json={"message": "I want one", "session_id": "offline-flow"},
    )
    assert order.status_code == 200
    assert '"type": "add_to_cart"' in order.text
    assert '"menu_item_id": "latte"' in order.text
    assert '"quantity": 1' in order.text
    assert '"fallback": false' in order.text


def test_complex_chat_uses_gemini_path_and_removes_markdown(client, fake_db, monkeypatch):
    _, user = _setup(client, fake_db)
    calls = []

    def fake_gemini(_service, prompt, context):
        calls.append({"prompt": prompt, "context": context})
        return "### Pick\nTry **Burger** for ৳200."

    monkeypatch.setattr(AIService, "_call_chat_gemini", fake_gemini)
    response = client.post(
        "/api/ai/chat",
        headers=user,
        json={
            "message": "Suggest something light with coffee under ৳300.",
            "session_id": "complex-flow",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(calls) == 1
    assert body["source"] == "gemini"
    assert body["fallback"] is False
    assert "**" not in body["response"]
    assert "###" not in body["response"]
    assert len(calls[0]["context"].get("recent_orders", [])) <= 3


def test_stream_first_chunk_deadline_returns_grounded_fallback(client, fake_db, monkeypatch):
    _, user = _setup(client, fake_db)
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "configured-for-test")
    monkeypatch.setattr(settings, "ai_chat_first_chunk_timeout_seconds", 0.04)
    monkeypatch.setattr(settings, "ai_chat_total_timeout_seconds", 0.2)

    def slow_stream(*_args, **_kwargs):
        time.sleep(0.12)
        yield "This chunk should arrive too late."

    monkeypatch.setattr(AIService, "_iter_chat_gemini", slow_stream)
    started = time.perf_counter()
    response = client.post(
        "/api/ai/chat/stream",
        headers=user,
        json={
            "message": "Suggest something filling but not too expensive.",
            "session_id": "slow-provider",
        },
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert 0.025 <= elapsed < 0.11
    assert '"fallback": true' in response.text
    assert '"source": "local"' in response.text
    assert "You could try" in response.text
    assert "Burger" in response.text
    assert "This chunk should arrive too late" not in response.text


def test_healthy_mocked_stream_completes_without_fallback(client, fake_db, monkeypatch):
    _, user = _setup(client, fake_db)
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "configured-for-test")
    monkeypatch.setattr(settings, "ai_chat_first_chunk_timeout_seconds", 0.1)
    monkeypatch.setattr(settings, "ai_chat_total_timeout_seconds", 0.3)

    def healthy_stream(*_args, **_kwargs):
        time.sleep(0.02)
        yield "Try **Burger** "
        time.sleep(0.01)
        yield "for ৳200."

    monkeypatch.setattr(AIService, "_iter_chat_gemini", healthy_stream)
    response = client.post(
        "/api/ai/chat/stream",
        headers=user,
        json={
            "message": "Suggest something filling but not too expensive.",
            "session_id": "healthy-provider",
        },
    )

    assert response.status_code == 200
    assert '"text": "Try Burger "' in response.text
    assert '"text": "for ৳200."' in response.text
    assert '"fallback": false' in response.text
    assert '"source": "gemini"' in response.text
    assert "**" not in response.text


def test_total_stream_deadline_stops_stalled_partial_response(client, fake_db, monkeypatch):
    _, user = _setup(client, fake_db)
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "configured-for-test")
    monkeypatch.setattr(settings, "ai_chat_first_chunk_timeout_seconds", 0.04)
    monkeypatch.setattr(settings, "ai_chat_total_timeout_seconds", 0.08)

    def stalled_stream(*_args, **_kwargs):
        yield "A grounded first chunk."
        time.sleep(0.15)
        yield "Too late."

    monkeypatch.setattr(AIService, "_iter_chat_gemini", stalled_stream)
    started = time.perf_counter()
    response = client.post(
        "/api/ai/chat/stream",
        headers=user,
        json={
            "message": "Suggest something filling but not too expensive.",
            "session_id": "stalled-provider",
        },
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed < 0.14
    assert "A grounded first chunk." in response.text
    assert "Too late." not in response.text
    assert '"fallback": true' in response.text
    assert '"source": "gemini"' in response.text
