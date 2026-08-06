"""Report aggregation — daily / monthly / popular items.

All calculations exclude cancelled orders from revenue and popularity.
CSV export is implemented per SRS.  Date ranges are interpreted in the
project timezone (Asia/Dhaka by default) and converted to UTC for
filtering.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.config import Settings
from app.models.schemas import DailyReport, MonthlyReport, OrderResponse, PopularItem
from app.repositories.orders import OrderRepository
from app.utils.timezone import (
    local_date_string,
    project_zone,
    to_local,
    to_utc,
    utcnow,
)


class ReportService:
    def __init__(self, orders: OrderRepository, settings: Settings):
        self._orders = orders
        self._settings = settings

    # -- daily ------------------------------------------------------------

    def daily(self, day: Optional[str] = None) -> DailyReport:
        if day:
            try:
                local_day = datetime.fromisoformat(day).date()
            except ValueError as exc:
                raise ValueError("invalid date; expected YYYY-MM-DD") from exc
        else:
            local_day = to_local(utcnow()).date()

        start_local = datetime.combine(local_day, datetime.min.time())
        end_local = start_local + timedelta(days=1)
        start_utc = to_utc(start_local.replace(tzinfo=project_zone())).isoformat()
        end_utc = to_utc(end_local.replace(tzinfo=project_zone())).isoformat()

        report = self._aggregate_window(start_utc, end_utc, exclude_cancelled_revenue=True)
        report_orders = [self._to_order_response(o) for o in report["orders"]]
        item_quantities = report["item_quantities"]

        total_revenue = report["revenue"]
        total_orders = report["order_count"]
        avg = round(total_revenue / total_orders, 2) if total_orders else 0.0

        return DailyReport(
            date=local_day.isoformat(),
            total_orders=total_orders,
            completed_orders=report["completed_count"],
            cancelled_orders=report["cancelled_count"],
            total_revenue=round(total_revenue, 2),
            average_order_value=avg,
            orders=report_orders,
            item_quantities=item_quantities,
        )

    # -- monthly ----------------------------------------------------------

    def monthly(self, year_month: Optional[str] = None) -> MonthlyReport:
        if year_month:
            try:
                year_str, month_str = year_month.split("-", 1)
                local_first = datetime(int(year_str), int(month_str), 1)
            except (ValueError, TypeError) as exc:
                raise ValueError("invalid month; expected YYYY-MM") from exc
        else:
            today = to_local(utcnow())
            local_first = datetime(year=today.year, month=today.month, day=1)

        if local_first.month == 12:
            next_month = datetime(year=local_first.year + 1, month=1, day=1)
        else:
            next_month = datetime(year=local_first.year, month=local_first.month + 1, day=1)

        start_local = datetime.combine(local_first.date(), datetime.min.time())
        end_local = datetime.combine(next_month.date(), datetime.min.time())
        start_utc = to_utc(start_local.replace(tzinfo=project_zone())).isoformat()
        end_utc = to_utc(end_local.replace(tzinfo=project_zone())).isoformat()

        # Collect every order in the month and group by local date.
        orders = self._orders.list_all()
        in_month: List[Dict[str, Any]] = []
        for order in orders:
            created = order.get("created_at")
            if not created:
                continue
            if isinstance(created, str) and (created < start_utc or created >= end_utc):
                continue
            in_month.append(order)

        total_orders = len(in_month)
        completed = sum(1 for o in in_month if o.get("status") == "completed")
        cancelled = sum(1 for o in in_month if o.get("status") == "cancelled")
        revenue = sum(
            float(o.get("total_amount") or 0)
            for o in in_month
            if o.get("status") not in {"cancelled"}
        )

        # Daily breakdown.
        per_day: Dict[str, Dict[str, Any]] = {}
        for order in in_month:
            created_raw = order.get("created_at")
            if not created_raw:
                continue
            try:
                created_dt = datetime.fromisoformat(created_raw)
            except ValueError:
                continue
            day_label = local_date_string(created_dt)
            bucket = per_day.setdefault(day_label, {"revenue": 0.0, "orders": 0})
            bucket["orders"] += 1
            if order.get("status") != "cancelled":
                bucket["revenue"] += float(order.get("total_amount") or 0)

        daily_breakdown = [
            {"date": label, "orders": data["orders"], "revenue": round(data["revenue"], 2)}
            for label, data in sorted(per_day.items())
        ]
        best_day = max(daily_breakdown, key=lambda row: row["revenue"], default=None)
        avg = round(revenue / total_orders, 2) if total_orders else 0.0

        return MonthlyReport(
            month=local_first.strftime("%Y-%m"),
            total_orders=total_orders,
            completed_orders=completed,
            cancelled_orders=cancelled,
            total_sales=round(revenue, 2),
            average_order_value=avg,
            daily_breakdown=daily_breakdown,
            best_day=best_day["date"] if best_day else None,
            best_day_revenue=best_day["revenue"] if best_day else 0.0,
        )

    # -- popular ----------------------------------------------------------

    def popular_items(
        self,
        limit: int = 10,
        category: Optional[str] = None,
    ) -> List[PopularItem]:
        counts: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"quantity": 0, "revenue": 0.0, "orders": set(), "name": "", "category": ""}
        )

        for order in self._orders.list_all():
            if order.get("status") == "cancelled":
                continue
            order_id = order.get("id", "")
            for item in order.get("items", []):
                item_id = item.get("menu_item_id") or item.get("name", "unknown")
                if category and item.get("category") and item.get("category") != category:
                    continue
                bucket = counts[item_id]
                bucket["name"] = item.get("name", bucket["name"])
                bucket["category"] = item.get("category", bucket["category"])
                bucket["quantity"] += int(item.get("quantity", 0))
                bucket["revenue"] += float(item.get("subtotal") or item.get("price", 0) * item.get("quantity", 0))
                if order_id:
                    bucket["orders"].add(order_id)

        ranked = sorted(
            counts.items(),
            key=lambda kv: (kv[1]["quantity"], kv[1]["revenue"]),
            reverse=True,
        )[:limit]

        return [
            PopularItem(
                rank=index + 1,
                item_id=key,
                name=info["name"] or key,
                category=info["category"],
                total_quantity=info["quantity"],
                order_count=len(info["orders"]),
                revenue=round(info["revenue"], 2),
            )
            for index, (key, info) in enumerate(ranked)
        ]

    # -- CSV --------------------------------------------------------------

    def daily_csv(self, day: Optional[str] = None) -> str:
        report = self.daily(day)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "date",
                "total_orders",
                "completed_orders",
                "cancelled_orders",
                "total_revenue",
                "average_order_value",
            ]
        )
        writer.writerow(
            [
                report.date,
                report.total_orders,
                report.completed_orders,
                report.cancelled_orders,
                f"{report.total_revenue:.2f}",
                f"{report.average_order_value:.2f}",
            ]
        )
        writer.writerow([])
        writer.writerow(["order_id", "status", "subtotal", "total", "created_at", "items"])
        for order in report.orders:
            writer.writerow(
                [
                    order.id,
                    order.status.value,
                    f"{order.subtotal:.2f}",
                    f"{order.total_amount:.2f}",
                    order.created_at,
                    "; ".join(f"{i.name} x{i.quantity}" for i in order.items),
                ]
            )
        return buffer.getvalue()

    def monthly_csv(self, year_month: Optional[str] = None) -> str:
        report = self.monthly(year_month)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "month",
                "total_orders",
                "completed_orders",
                "cancelled_orders",
                "total_sales",
                "average_order_value",
                "best_day",
                "best_day_revenue",
            ]
        )
        writer.writerow(
            [
                report.month,
                report.total_orders,
                report.completed_orders,
                report.cancelled_orders,
                f"{report.total_sales:.2f}",
                f"{report.average_order_value:.2f}",
                report.best_day or "",
                f"{report.best_day_revenue:.2f}",
            ]
        )
        writer.writerow([])
        writer.writerow(["date", "orders", "revenue"])
        for row in report.daily_breakdown:
            writer.writerow([row["date"], row["orders"], f"{row['revenue']:.2f}"])
        return buffer.getvalue()

    def popular_csv(self, limit: int = 10) -> str:
        items = self.popular_items(limit=limit)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "rank",
                "item_id",
                "name",
                "category",
                "total_quantity",
                "order_count",
                "revenue",
            ]
        )
        for item in items:
            writer.writerow(
                [
                    item.rank,
                    item.item_id,
                    item.name,
                    item.category,
                    item.total_quantity,
                    item.order_count,
                    f"{item.revenue:.2f}",
                ]
            )
        return buffer.getvalue()

    # -- internal --------------------------------------------------------

    def _aggregate_window(
        self,
        start_utc: str,
        end_utc: str,
        exclude_cancelled_revenue: bool = True,
    ) -> Dict[str, Any]:
        order_count = 0
        completed_count = 0
        cancelled_count = 0
        revenue = 0.0
        item_quantities: Dict[str, int] = defaultdict(int)
        window_orders: List[Dict[str, Any]] = []

        for order in self._orders.list_all():
            created = order.get("created_at")
            if not created:
                continue
            if isinstance(created, str) and (created < start_utc or created >= end_utc):
                continue
            order_count += 1
            window_orders.append(order)
            status = order.get("status")
            if status == "cancelled":
                cancelled_count += 1
                continue
            if status == "completed":
                completed_count += 1
            if exclude_cancelled_revenue:
                revenue += float(order.get("total_amount") or 0)
            for item in order.get("items", []):
                key = item.get("menu_item_id") or item.get("name", "unknown")
                item_quantities[key] += int(item.get("quantity", 0))

        return {
            "order_count": order_count,
            "completed_count": completed_count,
            "cancelled_count": cancelled_count,
            "revenue": revenue,
            "orders": window_orders,
            "item_quantities": dict(item_quantities),
        }

    def _to_order_response(self, order: Dict[str, Any]) -> OrderResponse:
        from app.services.orders import OrderService

        # Use the canonical response shaping from OrderService.  We build a
        # minimal instance rather than the full service graph because reports
        # only need the read-only projection.
        stub = OrderService.__new__(OrderService)
        return stub._to_response(order)  # type: ignore[attr-defined]