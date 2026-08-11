"""AI router — chat, recommendations, admin insights."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import (
    get_admin_user,
    get_ai_service,
    get_current_user,
)
from app.models.schemas import AIAssistantRequest, AIResponse, AIRecommendationResponse
from app.services.ai import AIService


router = APIRouter(prefix="/api", tags=["ai"])


@router.post("/ai/chat", response_model=AIResponse)
def chat(
    payload: AIAssistantRequest,
    current_user: dict = Depends(get_current_user),
    service: AIService = Depends(get_ai_service),
) -> AIResponse:
    return service.chat(prompt=payload.message, viewer=current_user)


@router.get("/ai/recommendations", response_model=AIRecommendationResponse)
def recommendations(
    current_user: dict = Depends(get_current_user),
    service: AIService = Depends(get_ai_service),
) -> AIRecommendationResponse:
    return service.recommend(viewer=current_user)


@router.get("/admin/ai/insights", response_model=AIResponse)
def admin_insights(
    _admin: dict = Depends(get_admin_user),
    service: AIService = Depends(get_ai_service),
) -> AIResponse:
    return service.admin_insights()
