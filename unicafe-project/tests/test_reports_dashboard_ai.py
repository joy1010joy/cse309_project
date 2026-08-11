"""Reports, dashboard, and AI contract tests."""
from __future__ import annotations

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
        json={"message": "What should I order?"},
    )
    assert chat.status_code == 200
    body = chat.json()
    assert "response" in body
    assert body["fallback"] is True
    assert "reply" not in body

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
