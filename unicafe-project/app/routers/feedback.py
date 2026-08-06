"""Feedback router — user feedback submission and admin listing."""
from __future__ import annotations

from typing import List, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import (
    get_admin_user,
    get_current_user,
    get_feedback_service,
)
from app.models.schemas import FeedbackCreate, FeedbackRecord
from app.services.feedback import FeedbackService
from app.services.utils import ServiceError


router = APIRouter(prefix="/api", tags=["feedback"])


def _raise_service_error(exc: ServiceError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.message,
    )


@router.post(
    "/feedback",
    response_model=FeedbackRecord,
    status_code=status.HTTP_201_CREATED,
)
def submit_feedback(
    payload: FeedbackCreate,
    current_user: dict = Depends(get_current_user),
    service: FeedbackService = Depends(get_feedback_service),
) -> FeedbackRecord:
    try:
        return service.submit(
            user=current_user,
            payload=payload,
        )
    except ServiceError as exc:
        _raise_service_error(exc)


@router.get(
    "/feedback",
    response_model=List[FeedbackRecord],
)
def list_feedback(
    _admin: dict = Depends(get_admin_user),
    service: FeedbackService = Depends(get_feedback_service),
) -> List[FeedbackRecord]:
    try:
        return [
            FeedbackRecord(**row)
            for row in service.list_all()
        ]
    except ServiceError as exc:
        _raise_service_error(exc)
