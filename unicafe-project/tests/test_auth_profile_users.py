"""Auth, profile, and admin-user API tests."""
from __future__ import annotations

from tests.conftest import auth_header, seed_user


def test_register_login_me(client):
    res = client.post(
        "/api/auth/register",
        json={
            "full_name": "Alice Student",
            "email": "alice@uni.edu",
            "password": "password1",
            "university_id": "STU-1001",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert "access_token" in body
    assert body["is_admin"] is False

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@uni.edu"
    assert "password_hash" not in me.json()


def test_duplicate_email_and_university_id(client, fake_db):
    seed_user(fake_db, email="bob@uni.edu", password="password1", university_id="STU-2002")
    res = client.post(
        "/api/auth/register",
        json={"full_name": "Bob", "email": "bob@uni.edu", "password": "password1"},
    )
    assert res.status_code == 409

    res = client.post(
        "/api/auth/register",
        json={
            "full_name": "Other",
            "email": "other@uni.edu",
            "password": "password1",
            "university_id": "STU-2002",
        },
    )
    assert res.status_code == 409


def test_bad_password_and_short_password(client, fake_db):
    seed_user(fake_db, email="carol@uni.edu", password="password1")
    bad = client.post("/api/auth/login", json={"email": "carol@uni.edu", "password": "wrongpass"})
    assert bad.status_code == 401

    short = client.post(
        "/api/auth/register",
        json={"full_name": "Short", "email": "short@uni.edu", "password": "short"},
    )
    assert short.status_code == 422


def test_disabled_user_login_and_token(client, fake_db):
    seed_user(fake_db, email="disabled@uni.edu", password="password1", is_active=False)
    login = client.post(
        "/api/auth/login",
        json={"email": "disabled@uni.edu", "password": "password1"},
    )
    assert login.status_code == 403

    seed_user(fake_db, email="active@uni.edu", password="password1", user_id="user_active")
    headers = auth_header(client, "active@uni.edu", "password1")
    fake_db.collection("users").document("user_active").update({"is_active": False})
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 403


def test_profile_safe_put_and_uniqueness(client, fake_db):
    seed_user(
        fake_db,
        email="p1@uni.edu",
        password="password1",
        university_id="UID-1",
        user_id="user_p1",
    )
    seed_user(
        fake_db,
        email="p2@uni.edu",
        password="password1",
        university_id="UID-2",
        user_id="user_p2",
    )
    headers = auth_header(client, "p1@uni.edu", "password1")

    ok = client.put(
        "/api/profile",
        headers=headers,
        json={"full_name": "Updated Name"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["full_name"] == "Updated Name"
    assert "password_hash" not in body
    assert "password" not in body

    conflict_email = client.put(
        "/api/profile",
        headers=headers,
        json={"email": "p2@uni.edu"},
    )
    assert conflict_email.status_code == 409

    conflict_uid = client.put(
        "/api/profile",
        headers=headers,
        json={"university_id": "UID-2"},
    )
    assert conflict_uid.status_code == 409


def test_admin_users_disable_enable_and_self_disable(client, fake_db):
    seed_user(
        fake_db,
        email="admin@uni.edu",
        password="password1",
        is_admin=True,
        user_id="admin_1",
    )
    seed_user(
        fake_db,
        email="member@uni.edu",
        password="password1",
        user_id="member_1",
    )
    admin = auth_header(client, "admin@uni.edu", "password1")

    listed = client.get("/api/admin/users", headers=admin)
    assert listed.status_code == 200
    for row in listed.json():
        assert "password_hash" not in row
        assert "password" not in row

    disabled = client.put(
        "/api/admin/users/member_1/status",
        headers=admin,
        json={"is_active": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False

    login = client.post(
        "/api/auth/login",
        json={"email": "member@uni.edu", "password": "password1"},
    )
    assert login.status_code == 403

    enabled = client.put(
        "/api/admin/users/member_1/status",
        headers=admin,
        json={"is_active": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["is_active"] is True

    self_disable = client.put(
        "/api/admin/users/admin_1/status",
        headers=admin,
        json={"is_active": False},
    )
    assert self_disable.status_code == 400

    member = auth_header(client, "member@uni.edu", "password1")
    forbidden = client.get("/api/admin/users", headers=member)
    assert forbidden.status_code == 403
