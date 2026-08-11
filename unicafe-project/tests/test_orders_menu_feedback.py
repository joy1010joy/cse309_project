"""Menu, inventory, order, notification, and feedback tests."""
from __future__ import annotations

from tests.conftest import auth_header, seed_menu_item, seed_user


def _admin_and_user(client, fake_db):
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
    return (
        auth_header(client, "admin@uni.edu", "password1"),
        auth_header(client, "student@uni.edu", "password1"),
    )


def test_menu_crud_and_inventory(client, fake_db):
    admin, _ = _admin_and_user(client, fake_db)

    created = client.post(
        "/api/admin/menu",
        headers=admin,
        json={
            "name": "Latte",
            "description": "Hot latte",
            "price": 120,
            "category": "Drinks",
            "stock_quantity": 5,
            "is_available": True,
        },
    )
    assert created.status_code == 201
    item_id = created.json()["id"]

    public = client.get("/api/menu")
    assert public.status_code == 200
    assert any(i["id"] == item_id for i in public.json())

    updated = client.put(
        f"/api/admin/menu/{item_id}",
        headers=admin,
        json={"price": 130},
    )
    assert updated.status_code == 200
    assert updated.json()["price"] == 130

    invalid = client.post(
        "/api/admin/menu",
        headers=admin,
        json={"name": "X", "description": "x", "price": -1, "category": "Drinks"},
    )
    assert invalid.status_code == 422

    no_token = client.post(
        "/api/admin/menu",
        json={
            "name": "Tea",
            "description": "Tea",
            "price": 50,
            "category": "Drinks",
            "stock_quantity": 1,
        },
    )
    assert no_token.status_code == 401

    stock = client.put(
        f"/api/admin/inventory/{item_id}",
        headers=admin,
        json={"stock_quantity": 0},
    )
    assert stock.status_code == 200
    assert stock.json()["stock_quantity"] == 0
    assert stock.json()["is_available"] is False

    stock2 = client.put(
        f"/api/admin/inventory/{item_id}",
        headers=admin,
        json={"stock_quantity": 4},
    )
    assert stock2.status_code == 200
    assert stock2.json()["is_available"] is True

    deleted = client.delete(f"/api/admin/menu/{item_id}", headers=admin)
    assert deleted.status_code == 204


def test_single_and_multi_item_orders_atomic(client, fake_db):
    admin, user = _admin_and_user(client, fake_db)
    seed_menu_item(fake_db, item_id="coffee", name="Coffee", price=100, stock=10)
    seed_menu_item(fake_db, item_id="sandwich", name="Sandwich", price=150, stock=5)

    order = client.post(
        "/api/orders",
        headers=user,
        json={"items": [{"menu_item_id": "coffee", "quantity": 3}]},
    )
    assert order.status_code == 201
    body = order.json()
    assert body["status"] == "pending"
    assert body["total_amount"] == 300
    order_id = body["id"]

    coffee = fake_db.collection("menu_items").document("coffee").get().to_dict()
    assert coffee["stock_quantity"] == 7

    too_many = client.post(
        "/api/orders",
        headers=user,
        json={"items": [{"menu_item_id": "coffee", "quantity": 8}]},
    )
    assert too_many.status_code == 400
    coffee = fake_db.collection("menu_items").document("coffee").get().to_dict()
    assert coffee["stock_quantity"] == 7

    history = client.get("/api/orders/history", headers=user)
    assert history.status_code == 200
    assert any(o["id"] == order_id for o in history.json())

    cancel = client.put(f"/api/orders/{order_id}/cancel", headers=user)
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"
    assert cancel.json()["stock_restored"] is True
    coffee = fake_db.collection("menu_items").document("coffee").get().to_dict()
    assert coffee["stock_quantity"] == 10

    cancel_again = client.put(f"/api/orders/{order_id}/cancel", headers=user)
    assert cancel_again.status_code == 400
    coffee = fake_db.collection("menu_items").document("coffee").get().to_dict()
    assert coffee["stock_quantity"] == 10

    multi = client.post(
        "/api/orders",
        headers=user,
        json={
            "items": [
                {"menu_item_id": "coffee", "quantity": 2},
                {"menu_item_id": "sandwich", "quantity": 1},
            ]
        },
    )
    assert multi.status_code == 201
    assert multi.json()["total_amount"] == 350
    assert fake_db.collection("menu_items").document("coffee").get().to_dict()["stock_quantity"] == 8
    assert fake_db.collection("menu_items").document("sandwich").get().to_dict()["stock_quantity"] == 4

    fail_multi = client.post(
        "/api/orders",
        headers=user,
        json={
            "items": [
                {"menu_item_id": "coffee", "quantity": 1},
                {"menu_item_id": "sandwich", "quantity": 99},
            ]
        },
    )
    assert fail_multi.status_code == 400
    assert fake_db.collection("menu_items").document("coffee").get().to_dict()["stock_quantity"] == 8
    assert fake_db.collection("menu_items").document("sandwich").get().to_dict()["stock_quantity"] == 4


def test_order_status_workflow_and_notifications(client, fake_db):
    admin, user = _admin_and_user(client, fake_db)
    seed_menu_item(fake_db, item_id="tea", name="Tea", price=80, stock=20)

    created = client.post(
        "/api/orders",
        headers=user,
        json={"items": [{"menu_item_id": "tea", "quantity": 1}]},
    )
    order_id = created.json()["id"]

    # invalid transition
    bad = client.put(
        f"/api/admin/orders/{order_id}/status",
        headers=admin,
        json={"status": "ready"},
    )
    assert bad.status_code == 400

    for status in ("confirmed", "preparing", "ready", "completed"):
        res = client.put(
            f"/api/admin/orders/{order_id}/status",
            headers=admin,
            json={"status": status},
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == status

    completed = client.get(f"/api/orders/{order_id}", headers=user)
    assert completed.json()["confirmed_at"]
    assert completed.json()["ready_at"]
    assert completed.json()["completed_at"]

    forbidden = client.put(
        f"/api/admin/orders/{order_id}/status",
        headers=user,
        json={"status": "pending"},
    )
    assert forbidden.status_code == 403

    notes = client.get("/api/notifications", headers=user)
    assert notes.status_code == 200
    types = {n["type"] for n in notes.json()}
    assert "order_placed" in types
    assert "order_confirmed" in types
    assert "order_preparing" in types
    assert "order_ready" in types
    assert "order_completed" in types
    assert "feedback_request" in types

    unread = client.get("/api/notifications/unread-count", headers=user)
    assert unread.status_code == 200
    assert unread.json()["unread"] > 0

    first_id = notes.json()[0]["id"]
    marked = client.put(f"/api/notifications/{first_id}/read", headers=user)
    assert marked.status_code == 200
    assert marked.json()["is_read"] is True

    all_read = client.put("/api/notifications/read-all", headers=user)
    assert all_read.status_code == 200
    unread2 = client.get("/api/notifications/unread-count", headers=user)
    assert unread2.json()["unread"] == 0


def test_feedback_rules(client, fake_db):
    admin, user = _admin_and_user(client, fake_db)
    seed_user(
        fake_db,
        email="other@uni.edu",
        password="password1",
        user_id="other_1",
    )
    other = auth_header(client, "other@uni.edu", "password1")
    seed_menu_item(fake_db, item_id="juice", name="Juice", price=90, stock=10)

    order = client.post(
        "/api/orders",
        headers=user,
        json={"items": [{"menu_item_id": "juice", "quantity": 1}]},
    ).json()
    order_id = order["id"]

    early = client.post(
        "/api/feedback",
        headers=user,
        json={"order_id": order_id, "rating": 5, "comment": "too early"},
    )
    assert early.status_code == 400

    for status in ("confirmed", "preparing", "ready", "completed"):
        assert (
            client.put(
                f"/api/admin/orders/{order_id}/status",
                headers=admin,
                json={"status": status},
            ).status_code
            == 200
        )

    stolen = client.post(
        "/api/feedback",
        headers=other,
        json={"order_id": order_id, "rating": 4},
    )
    assert stolen.status_code == 403

    invalid_rating = client.post(
        "/api/feedback",
        headers=user,
        json={"order_id": order_id, "rating": 9},
    )
    assert invalid_rating.status_code == 422

    ok = client.post(
        "/api/feedback",
        headers=user,
        json={"order_id": order_id, "rating": 5, "comment": "Great"},
    )
    assert ok.status_code == 201
    assert "password_hash" not in ok.json()

    dup = client.post(
        "/api/feedback",
        headers=user,
        json={"order_id": order_id, "rating": 4},
    )
    assert dup.status_code == 409

    listed = client.get("/api/feedback", headers=admin)
    assert listed.status_code == 200
    assert any(f["order_id"] == order_id for f in listed.json())
