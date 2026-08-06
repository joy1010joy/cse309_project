"""Feedback router — user feedback submission + admin read."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import (
    get_admin_user,
    get_current_user,
    get_feedback_service,
)
from app.models.schemas import FeedbackCreate, FeedbackResponse
from app.services.feedback import FeedbackService
from app.services.utils import ServiceError


router = APIRouter(prefix="/api", tags=["feedback"])


def _raise(exc: ServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def submit_feedback(
    payload: FeedbackCreate,
    current_user: dict = Depends(get_current_user),
    service: FeedbackService = Depends(get_feedback_service),
) -> FeedbackResponse:
    try:
        result = service.create(user_id=current_user["id"], payload=payload)
    except ServiceError as exc:
        _raise(exc)
    return FeedbackResponse(**result)


@router.get("/feedback", response_model=List[FeedbackResponse])
def list_feedback(
    _admin: dict = Depends(get_admin_user),
    service: FeedbackService = Depends(get_feedback_service),
) -> List[FeedbackResponse]:
    return [FeedbackResponse(**row) for row in service.list_all()]