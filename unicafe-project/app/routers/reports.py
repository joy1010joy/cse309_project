"""Reports router — admin analytics + CSV exports."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from app.dependencies import get_admin_user, get_report_service
from app.models.schemas import DailyReport, MonthlyReport, PopularItem
from app.services.reports import ReportService
from app.services.utils import ServiceError


router = APIRouter(prefix="/api/admin/reports", tags=["reports"])


@router.get("/daily", response_model=DailyReport)
def daily(
    day: Optional[str] = Query(default=None, description="YYYY-MM-DD (local)"),
    _admin: dict = Depends(get_admin_user),
    service: ReportService = Depends(get_report_service),
) -> DailyReport:
    try:
        return service.daily(day)
    except ValueError as exc:
        raise ServiceError(str(exc), 400) from exc


@router.get("/monthly", response_model=MonthlyReport)
def monthly(
    year_month: Optional[str] = Query(default=None, description="YYYY-MM (local)"),
    _admin: dict = Depends(get_admin_user),
    service: ReportService = Depends(get_report_service),
) -> MonthlyReport:
    try:
        return service.monthly(year_month)
    except ValueError as exc:
        raise ServiceError(str(exc), 400) from exc


@router.get("/popular-items")
def popular_items(
    limit: int = Query(default=10, ge=1, le=100),
    category: Optional[str] = Query(default=None),
    _admin: dict = Depends(get_admin_user),
    service: ReportService = Depends(get_report_service),
) -> list[PopularItem]:
    return service.popular_items(limit=limit, category=category)


@router.get("/export")
def export_csv(
    report: str = Query("daily", pattern="^(daily|monthly|popular)$"),
    day: Optional[str] = Query(default=None),
    year_month: Optional[str] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    _admin: dict = Depends(get_admin_user),
    service: ReportService = Depends(get_report_service),
) -> PlainTextResponse:
    if report == "daily":
        body = service.daily_csv(day)
        filename = f"daily_{day or 'today'}.csv"
    elif report == "monthly":
        body = service.monthly_csv(year_month)
        filename = f"monthly_{year_month or 'current'}.csv"
    else:
        body = service.popular_csv(limit=limit)
        filename = "popular_items.csv"
    return PlainTextResponse(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )