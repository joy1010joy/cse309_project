"""Admin dashboard router — overview stats, peak hours, top items."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.dependencies import get_admin_user, get_dashboard_service
from app.services.dashboard import DashboardService


router = APIRouter(prefix="/api/admin/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(
    _admin: dict = Depends(get_admin_user),
    service: DashboardService = Depends(get_dashboard_service),
) -> Dict[str, Any]:
    stats = service.stats()
    try:
        stats["peak_hours"] = service.peak_hours()
    except Exception:
        stats["peak_hours"] = []
    try:
        stats["top_items"] = service.top_items()
    except Exception:
        stats["top_items"] = []
    return stats