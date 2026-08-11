"""Shared pytest fixtures — FakeFirestore only, never production Firestore."""
from __future__ import annotations

import os
from typing import Generator

import pytest
from fastapi.testclient import TestClient

# Ensure settings are test-safe before importing the app.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unicafe-pytest")
os.environ["ADMIN_EMAIL"] = ""
os.environ["ADMIN_PASSWORD"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ.pop("FIREBASE_CREDENTIALS_PATH", None)
os.environ.pop("FIRESTORE_EMULATOR_HOST", None)

from app.config import reset_settings_cache  # noqa: E402
from app.db import reset_db, use_database  # noqa: E402
from app.repositories.fake import FakeFirestore  # noqa: E402
from app.utils.security import hash_password  # noqa: E402
from app.utils.timezone import to_iso, utcnow  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture()
def fake_db() -> Generator[FakeFirestore, None, None]:
    reset_settings_cache()
    reset_db()
    db = FakeFirestore()
    use_database(db)
    yield db
    reset_db()
    reset_settings_cache()


@pytest.fixture()
def client(fake_db: FakeFirestore) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def seed_user(
    db: FakeFirestore,
    *,
    email: str,
    password: str,
    full_name: str = "Test User",
    is_admin: bool = False,
    is_active: bool = True,
    university_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    doc_id = user_id or f"user_{email.split('@')[0]}"
    now = to_iso(utcnow())
    data = {
        "id": doc_id,
        "email": email.lower(),
        "uid": university_id,
        "full_name": full_name,
        "password_hash": hash_password(password),
        "is_admin": is_admin,
        "is_active": is_active,
        "created_at": now,
        "updated_at": now,
    }
    db.collection("users").document(doc_id).set(data)
    return data


def seed_menu_item(
    db: FakeFirestore,
    *,
    item_id: str,
    name: str,
    price: float = 100.0,
    stock: int = 10,
    category: str = "Drinks",
    is_available: bool = True,
) -> dict:
    now = to_iso(utcnow())
    data = {
        "id": item_id,
        "name": name,
        "description": f"{name} description",
        "price": price,
        "category": category,
        "stock_quantity": stock,
        "is_available": is_available and stock > 0,
        "created_at": now,
        "updated_at": now,
    }
    db.collection("menu_items").document(item_id).set(data)
    return data


def auth_header(client: TestClient, email: str, password: str) -> dict:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
