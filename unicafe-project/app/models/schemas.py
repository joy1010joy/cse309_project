"""Pydantic request and response models for the public API.

The schemas in this file act as the canonical contract between the
service layer and the FastAPI routers.  Validation rules (email format,
password length, rating range, status transitions, etc.) live here so the
service layer can assume well-formed inputs.
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


PASSWORD_MIN_LENGTH = 8
COMMENT_MAX_LENGTH = 1000
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
UNIVERSITY_ID_REGEX = re.compile(r"^[A-Za-z0-9-]{4,32}$")


class OrderStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# Logical status transitions used by order endpoints.
ALLOWED_TRANSITIONS: Dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY},
    OrderStatus.READY: {OrderStatus.COMPLETED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class UserRegister(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=128)
    university_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Full name is required")
        return cleaned

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not EMAIL_REGEX.match(cleaned):
            raise ValueError("Invalid email address")
        return cleaned

    @field_validator("university_id")
    @classmethod
    def _check_uid(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not UNIVERSITY_ID_REGEX.match(cleaned):
            raise ValueError(
                "University ID must be 4-32 characters of letters, digits, or dashes"
            )
        return cleaned


class UserLogin(BaseModel):
    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not EMAIL_REGEX.match(cleaned):
            raise ValueError("Invalid email address")
        return cleaned


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    is_admin: bool
    user_id: str


class UserPublic(BaseModel):
    id: str
    email: str
    full_name: str
    university_id: Optional[str] = None
    is_admin: bool
    is_active: bool
    created_at: str


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    email: Optional[str] = Field(default=None, min_length=3, max_length=200)
    university_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Full name is required")
        return cleaned

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if not EMAIL_REGEX.match(cleaned):
            raise ValueError("Invalid email address")
        return cleaned

    @field_validator("university_id")
    @classmethod
    def _check_uid(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not UNIVERSITY_ID_REGEX.match(cleaned):
            raise ValueError(
                "University ID must be 4-32 characters of letters, digits, or dashes"
            )
        return cleaned


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------


class MenuItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=1, max_length=600)
    price: float = Field(..., gt=0, le=10000)
    category: str = Field(..., min_length=1, max_length=80)
    stock_quantity: int = Field(0, ge=0, le=100000)
    is_available: bool = True

    @field_validator("name", "description", "category")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned


class MenuItemUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=600)
    price: Optional[float] = Field(default=None, gt=0, le=10000)
    category: Optional[str] = Field(default=None, max_length=80)
    stock_quantity: Optional[int] = Field(default=None, ge=0, le=100000)
    is_available: Optional[bool] = None

    @field_validator("name", "description", "category")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned


class MenuItemResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    price: float
    category: str
    stock_quantity: int = 0
    is_available: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


class OrderItemCreate(BaseModel):
    menu_item_id: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0, le=200)


class OrderCreate(BaseModel):
    items: List[OrderItemCreate] = Field(..., min_length=1)
    pickup_time: Optional[datetime] = None

    @model_validator(mode="after")
    def _no_duplicates(self) -> "OrderCreate":
        seen: set[str] = set()
        for item in self.items:
            if item.menu_item_id in seen:
                raise ValueError("Duplicate menu items are not allowed in one order")
            seen.add(item.menu_item_id)
        return self


class OrderItemSnapshot(BaseModel):
    menu_item_id: str
    name: str
    quantity: int
    price: float
    subtotal: float


class OrderResponse(BaseModel):
    id: str
    user_id: str
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    status: OrderStatus
    subtotal: float
    total_amount: float
    pickup_time: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None
    confirmed_at: Optional[str] = None
    ready_at: Optional[str] = None
    completed_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    items: List[OrderItemSnapshot]
    feedback_id: Optional[str] = None
    stock_restored: bool = False


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


class InventoryUpdate(BaseModel):
    item_id: str = Field(..., min_length=1)
    stock_quantity: int = Field(..., ge=0, le=100000)


class InventoryRecord(BaseModel):
    id: str
    name: str
    category: str
    price: float
    stock_quantity: int
    is_available: bool


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


class FeedbackCreate(BaseModel):
    order_id: str = Field(..., min_length=1)
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=COMMENT_MAX_LENGTH)

    @field_validator("comment")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class FeedbackRecord(BaseModel):
    id: str
    user_id: str
    user_name: str = ""
    order_id: str
    rating: int
    comment: Optional[str] = None
    created_at: str


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class NotificationType(str, Enum):
    ORDER_PLACED = "order_placed"
    ORDER_CONFIRMED = "order_confirmed"
    ORDER_PREPARING = "order_preparing"
    ORDER_READY = "order_ready"
    ORDER_COMPLETED = "order_completed"
    ORDER_CANCELLED = "order_cancelled"
    FEEDBACK_REQUEST = "feedback_request"
    SYSTEM = "system"

    @classmethod
    def coerce(cls, value: Any) -> str:
        try:
            return cls(value).value
        except (ValueError, TypeError):
            return cls.SYSTEM.value


class NotificationRecord(BaseModel):
    id: str
    user_id: str
    type: str
    title: str
    message: str
    order_id: Optional[str] = None
    is_read: bool = False
    created_at: str
    read_at: Optional[str] = None
    dedupe_key: Optional[str] = None


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------


class AIAssistantRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)


class AIResponse(BaseModel):
    response: str
    fallback: bool = False


class AIRecommendationItem(BaseModel):
    menu_item_id: str
    name: str
    reason: str = ""
    price: float = 0.0
    category: str = ""


class AIRecommendationResponse(BaseModel):
    recommendations: List[AIRecommendationItem]
    fallback: bool = False


# ---------------------------------------------------------------------------
# Admin user management
# ---------------------------------------------------------------------------


class AdminUserStatusUpdate(BaseModel):
    is_active: bool


class AdminUserSummary(BaseModel):
    id: str
    full_name: str
    email: str
    university_id: Optional[str] = None
    is_admin: bool
    is_active: bool
    created_at: str
    order_count: int = 0
    total_spent: float = 0.0


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


class DailyReport(BaseModel):
    date: str
    total_orders: int = 0
    completed_orders: int = 0
    cancelled_orders: int = 0
    total_revenue: float = 0.0
    average_order_value: float = 0.0
    orders: List[OrderResponse] = Field(default_factory=list)
    item_quantities: Dict[str, int] = Field(default_factory=dict)


class MonthlyReport(BaseModel):
    month: str
    total_orders: int = 0
    completed_orders: int = 0
    cancelled_orders: int = 0
    total_sales: float = 0.0
    average_order_value: float = 0.0
    daily_breakdown: List[Dict[str, Any]] = Field(default_factory=list)
    best_day: Optional[str] = None
    best_day_revenue: float = 0.0


class PopularItem(BaseModel):
    rank: int
    item_id: str
    name: str
    category: str = ""
    total_quantity: int = 0
    order_count: int = 0
    revenue: float = 0.0