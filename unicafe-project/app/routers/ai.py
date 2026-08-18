"""AI router — chat, recommendations, admin insights."""
from __future__ import annotations

import json
from typing import Any, Dict, Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

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
    return service.chat(
        prompt=payload.message,
        viewer=current_user,
        session_id=payload.session_id,
    )


def _sse(event: Dict[str, Any]) -> str:
    name = str(event.get("event") or "message")
    payload = {key: value for key, value in event.items() if key != "event"}
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/ai/chat/stream")
def chat_stream(
    payload: AIAssistantRequest,
    current_user: dict = Depends(get_current_user),
    service: AIService = Depends(get_ai_service),
) -> StreamingResponse:
    def events() -> Iterator[str]:
        yield _sse({"event": "ready"})
        for event in service.chat_stream(
            prompt=payload.message,
            viewer=current_user,
            session_id=payload.session_id,
        ):
            yield _sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
