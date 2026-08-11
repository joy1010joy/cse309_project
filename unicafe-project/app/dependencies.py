"""FastAPI dependencies — DB injection, authentication, role guards."""
from __future__ import annotations
from typing import Optional
from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.db import get_db
from app.repositories.base import Database
from app.repositories.feedback import FeedbackRepository
from app.repositories.inventory import InventoryRepository
from app.repositories.menu import MenuRepository
from app.repositories.notifications import NotificationRepository
from app.repositories.orders import OrderRepository
from app.repositories.users import UserRepository
from app.services.ai import AIService
from app.services.auth import AuthService
from app.services.dashboard import DashboardService
from app.services.feedback import FeedbackService
from app.services.menu import MenuService
from app.services.notifications import NotificationService
from app.services.orders import OrderService
from app.services.reports import ReportService
from app.services.users import UserService
from app.services.inventory import InventoryService
from app.utils.security import TokenError, decode_access_token


def get_database() -> Database:
    return get_db()


def get_user_repository(db: Database = Depends(get_database)) -> UserRepository:
    return UserRepository(db)


def get_menu_repository(db: Database = Depends(get_database)) -> MenuRepository:
    return MenuRepository(db)


def get_order_repository(db: Database = Depends(get_database)) -> OrderRepository:
    return OrderRepository(db)


def get_inventory_repository(db: Database = Depends(get_database)) -> InventoryRepository:
    return InventoryRepository(db)


def get_feedback_repository(db: Database = Depends(get_database)) -> FeedbackRepository:
    return FeedbackRepository(db)


def get_notification_repository(db: Database = Depends(get_database)) -> NotificationRepository:
    return NotificationRepository(db)


# -- services ----------------------------------------------------------------


def get_auth_service(
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(users=users, settings=settings)


def get_menu_service(
    menu: MenuRepository = Depends(get_menu_repository),
) -> MenuService:
    return MenuService(menu=menu)


def get_notification_service(
    notifications: NotificationRepository = Depends(get_notification_repository),
    settings: Settings = Depends(get_settings),
) -> NotificationService:
    return NotificationService(notifications=notifications, settings=settings)


def get_feedback_service(
    feedback: FeedbackRepository = Depends(get_feedback_repository),
    orders: OrderRepository = Depends(get_order_repository),
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> FeedbackService:
    return FeedbackService(feedback=feedback, orders=orders, users=users, settings=settings)


def get_user_service(users: UserRepository = Depends(get_user_repository)) -> UserService:
    return UserService(users=users)


def get_dashboard_service(
    orders: OrderRepository = Depends(get_order_repository),
    menu: MenuRepository = Depends(get_menu_repository),
    users: UserRepository = Depends(get_user_repository),
    feedback: FeedbackRepository = Depends(get_feedback_repository),
) -> DashboardService:
    return DashboardService(orders=orders, menu=menu, users=users, feedback=feedback)


def get_report_service(
    orders: OrderRepository = Depends(get_order_repository),
    menu: MenuRepository = Depends(get_menu_repository),
    settings: Settings = Depends(get_settings),
) -> ReportService:
    return ReportService(orders=orders, settings=settings, menu=menu)


def get_ai_service(
    menu: MenuRepository = Depends(get_menu_repository),
    orders: OrderRepository = Depends(get_order_repository),
    settings: Settings = Depends(get_settings),
) -> AIService:
    return AIService(menu=menu, orders=orders, settings=settings)


def get_inventory_service(
    inventory: InventoryRepository = Depends(get_inventory_repository),
) -> "InventoryService":
    from app.services.inventory import InventoryService  # local import to avoid cycle

    return InventoryService(inventory=inventory)


# Real OrderService wiring is below so we can inject the notification service
# without a circular import at module load time.


def build_order_service(
    db: Database,
    settings: Settings,
    notifications: NotificationService,
) -> OrderService:
    """Build an :class:`OrderService` with the notification service wired in.

    Used as the FastAPI dependency so the dependency graph stays explicit and
    the routers remain easy to test.
    """

    return OrderService(
        db=db,
        settings=settings,
        orders=OrderRepository(db),
        menu=MenuRepository(db),
        inventory=InventoryRepository(db),
        users=UserRepository(db),
        notifications=notifications,
    )


def get_order_service_dep(
    db: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    notifications: NotificationService = Depends(get_notification_service),
) -> OrderService:
    return build_order_service(db=db, settings=settings, notifications=notifications)


# -- auth guards -------------------------------------------------------------


def _extract_bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return authorization.split(" ", 1)[1].strip()


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    settings: Settings = Depends(get_settings),
    users: UserRepository = Depends(get_user_repository),
) -> dict:
    token = _extract_bearer(authorization)
    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token missing subject claim",
        )

    user = users.get(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user not found",
        )
    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="account disabled",
        )
    return user


def get_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin privileges required",
        )
    return current_user


# Public re-export of the dependency callable so routers can import it
# without knowing which version is the "real" implementation.  This is the
# canonical accessor used by :mod:`app.routers.orders`.
get_order_service = get_order_service_dep