"""Notifications router — user inbox and admin broadcasts."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import (
    get_current_user,
    get_notification_service,
)
from app.models.schemas import NotificationResponse
from app.services.notifications import NotificationService
from app.services.utils import ServiceError


router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _raise(exc: ServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("", response_model=List[NotificationResponse])
def list_notifications(
    current_user: dict = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> List[NotificationResponse]:
    return [NotificationResponse(**row) for row in service.list_for_user(user_id=current_user["id"])]


@router.put("/read-all")
def mark_all_read(
    current_user: dict = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> dict:
    updated = service.mark_all_read(user_id=current_user["id"])
    return {"updated": updated}


@router.put("/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    try:
        row = service.mark_read(user_id=current_user["id"], notification_id=notification_id)
    except ServiceError as exc:
        _raise(exc)
    return NotificationResponse(**row)


@router.get("/unread-count")
def unread_count(
    current_user: dict = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> dict:
    return {"unread": service.unread_count(user_id=current_user["id"])}