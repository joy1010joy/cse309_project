"""AI router — chat, recommendations, admin insights."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import (
    get_admin_user,
    get_ai_service,
    get_current_user,
    get_menu_service,
)
from app.models.schemas import AIAssistantRequest, AIResponse, AIRecommendationResponse
from app.services.ai import AIService
from app.services.menu import MenuService


router = APIRouter(prefix="/api", tags=["ai"])


def _raise(exc: Exception) -> None:
    raise HTTPException(status_code=500, detail=str(exc))


@router.post("/ai/chat", response_model=AIResponse)
def chat(
    payload: AIAssistantRequest,
    _user: dict = Depends(get_current_user),
    service: AIService = Depends(get_ai_service),
) -> AIResponse:
    return service.chat(user_id=payload.user_id, message=payload.message)


@router.get("/ai/recommendations", response_model=AIRecommendationResponse)
def recommendations(
    user_id: str,
    _user: dict = Depends(get_current_user),
    service: AIService = Depends(get_ai_service),
    menu: MenuService = Depends(get_menu_service),
) -> AIRecommendationResponse:
    items = menu.list_items(available_only=False)
    return service.recommend(user_id=user_id, menu_items=items)


@router.get("/admin/ai/insights")
def admin_insights(
    _admin: dict = Depends(get_admin_user),
    service: AIService = Depends(get_ai_service),
) -> dict:
    return service.admin_insights()