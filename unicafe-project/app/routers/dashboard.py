"""Admin dashboard router — overview KPIs."""
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
    return service.stats()
