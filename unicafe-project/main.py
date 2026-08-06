"""FastAPI entrypoint for the UniCafe project.

This module is intentionally thin: it wires routers, mounts the static
frontend, enables CORS, exposes a health endpoint, and seeds the default
admin account on startup if env credentials are present.

All business logic lives under the :mod:`app` package.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import get_db, reset_db
from app.repositories.users import UserRepository
from app.services.auth import AuthService
from app.routers import (
    ai as ai_router,
    auth as auth_router,
    dashboard as dashboard_router,
    feedback as feedback_router,
    inventory as inventory_router,
    menu as menu_router,
    notifications as notifications_router,
    orders as orders_router,
    reports as reports_router,
    users as users_router,
)


logger = logging.getLogger("unicafe")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s"
)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    settings = get_settings()
    db = get_db()
    if db is None:
        logger.warning(
            "Firestore backend is unavailable.  Set FIREBASE_CREDENTIALS_PATH "
            "or run via the Firebase emulator.  The /api endpoints will return 503."
        )
    else:
        if settings.admin_email and settings.admin_password:
            try:
                auth_service = AuthService(
                    users=UserRepository(db),
                    settings=settings,
                )
                created = auth_service.seed_default_admin()

                if created:
                    logger.info(
                        "Default admin account created: %s",
                        settings.admin_email,
                    )
                else:
                    logger.info(
                        "Default admin account already exists or was skipped"
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to seed default admin: %s", exc)

    yield

    # Reset module-level state between processes — only affects the in-memory
    # fallback used by tests, so it's safe to leave in production.
    reset_db()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="UniCafe API",
        description="University cafe food pre-order platform.",
        version="2.0.0",
        lifespan=lifespan,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # -- API routers ------------------------------------------------------
    app.include_router(auth_router.router)

    app.include_router(menu_router.public_router)
    app.include_router(menu_router.admin_router)

    app.include_router(orders_router.user_router)
    app.include_router(orders_router.admin_router)

    app.include_router(users_router.router)
    app.include_router(users_router.admin_router)

    app.include_router(feedback_router.router)
    app.include_router(notifications_router.router)
    app.include_router(reports_router.router)
    app.include_router(dashboard_router.router)
    app.include_router(ai_router.router)
    app.include_router(inventory_router.router)

    # -- health ----------------------------------------------------------
    @app.get("/api/health", tags=["health"])
    def health() -> dict:
        db = get_db()
        return {
            "status": "ok" if db is not None else "degraded",
            "database": "firestore" if db is not None else "unavailable",
        }

    # -- static frontend -------------------------------------------------
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
