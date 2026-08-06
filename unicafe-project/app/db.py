"""Database wiring.

The application talks to data through the abstract :class:`Database` interface
defined in :mod:`app.repositories.base`.  In production we use the real
Firestore client.  Tests substitute :class:`FakeFirestore` directly via
:func:`use_database` without ever touching Firebase Admin SDK.

This module deliberately avoids initialising Firebase at import time so that
``from app.main import app`` works on machines without credentials (e.g. CI,
tests, ``pytest -q``).
"""
from __future__ import annotations

import os
import threading
from typing import Optional

from app.config import get_settings
from app.repositories.base import Database
from app.repositories.fake import FakeFirestore
from app.repositories.firestore import RealFirestoreAdapter

_db: Optional[Database] = None
_lock = threading.Lock()
_initialised = False


def _init_firebase() -> Optional[Database]:
    """Attempt to build the real Firestore adapter.

    Returns ``None`` if credentials are missing or Firebase Admin SDK fails to
    initialise.  Callers should fall back to the fake database in that case so
    that the app can still import and run tests.
    """

    settings = get_settings()
    cred_path = settings.firebase_credentials_path
    emulator = settings.firebase_emulator_host

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except Exception:  # pragma: no cover - dependency missing
        return None

    try:
        firebase_admin.get_app()
    except ValueError:
        try:
            if cred_path and os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
            elif emulator:
                os.environ.setdefault("GCLOUD_PROJECT", "demo-unicafe")
                cred = credentials.ApplicationDefault()
            else:
                return None
            firebase_admin.initialize_app(cred)
        except Exception:
            return None

    try:
        client = firestore.client()
    except Exception:
        return None

    return RealFirestoreAdapter(client)


def get_db() -> Database:
    """Return the application database.

    On first call, attempts to build the real Firestore adapter.  If that
    fails (no credentials, no emulator, SDK missing), the result is *not*
    cached and a warning is logged; callers should detect the failure and
    substitute :class:`FakeFirestore` using :func:`use_database`.
    """

    global _db, _initialised
    with _lock:
        if _db is not None:
            return _db
        if _initialised:
            return _db  # type: ignore[return-value]
        backend = _init_firebase()
        if backend is not None:
            _db = backend
            _initialised = True
        return _db  # type: ignore[return-value]


def use_database(backend: Database) -> Database:
    """Force the database layer to use ``backend`` (used by tests)."""

    global _db, _initialised
    with _lock:
        _db = backend
        _initialised = True
    return backend


def reset_db() -> None:
    """Drop the cached database (test helper)."""

    global _db, _initialised
    with _lock:
        _db = None
        _initialised = False


def fake_db() -> FakeFirestore:
    """Return a fresh in-memory fake database (used by tests)."""

    return FakeFirestore()