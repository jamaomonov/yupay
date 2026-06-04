"""Pydantic DTOs for the admin Dashboard payload."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict


class CurrencyAmount(BaseModel):
    currency: str
    amount: Decimal


class StatusCount(BaseModel):
    status: str
    count: int


class DayBucket(BaseModel):
    """One day in a sparkline series."""

    date: str  # ISO date, e.g. "2026-05-17"
    count: int
    revenue_usd: Decimal


class InventorySummary(BaseModel):
    available: int
    reserved: int
    issued: int
    voided: int
    low_stock_skus: int  # SKUs with available < threshold


class DashboardOut(BaseModel):
    """Single payload behind ``GET /admin/stats/dashboard``."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    window_hours: int

    orders_in_window: int
    orders_delivered_in_window: int
    orders_failed_in_window: int

    revenue_in_window: list[CurrencyAmount]
    status_breakdown: list[StatusCount]

    in_flight_tasks: int
    stuck_payments: int  # pending payments older than 1 hour
    pending_orders: int  # pending_payment older than 5 minutes

    inventory: InventorySummary

    orders_last_7_days: list[DayBucket]


class AnalyticsRange(str, Enum):
    """Selectable analytics window."""

    D7 = "7d"
    D30 = "30d"
    D90 = "90d"


def range_to_days(r: AnalyticsRange) -> int:
    """Map a range enum to its day count."""
    return {AnalyticsRange.D7: 7, AnalyticsRange.D30: 30, AnalyticsRange.D90: 90}[r]


# ---- business tab ----


class RevenuePoint(BaseModel):
    date: date
    revenue_usd: Decimal
    orders: int


class FunnelOut(BaseModel):
    created: int
    paid: int
    fulfilling: int
    delivered: int
    cancelled: int
    expired: int
    refunded: int
    payment_conversion_pct: float


class BrandRevenueOut(BaseModel):
    slug: str
    revenue_usd: Decimal
    units: int
    margin_usd: Decimal | None


class SkuRevenueOut(BaseModel):
    sku_code: str
    revenue_usd: Decimal
    units: int
    margin_usd: Decimal | None


class LocaleCountOut(BaseModel):
    locale: str
    users: int


class NewUsersPoint(BaseModel):
    date: date
    users: int


class BusinessSummaryOut(BaseModel):
    gmv_usd: Decimal
    orders: int
    paid_orders: int
    delivered_orders: int
    aov_usd: Decimal
    fx_pnl_usd: Decimal
    gross_margin_usd: Decimal
    margin_pct: float
    margin_approx: bool
    margin_unknown_units: int


class CustomersOut(BaseModel):
    new_users_series: list[NewUsersPoint]
    guest_orders: int
    registered_orders: int
    repeat_rate_pct: float
    top_locales: list[LocaleCountOut]


class BusinessAnalyticsOut(BaseModel):
    generated_at: datetime
    range: AnalyticsRange
    summary: BusinessSummaryOut
    revenue_series: list[RevenuePoint]
    funnel: FunnelOut
    top_brands: list[BrandRevenueOut]
    top_skus: list[SkuRevenueOut]
    customers: CustomersOut


# ---- ops tab ----


class ProviderStatOut(BaseModel):
    provider: str
    count: int
    volume_usd: Decimal
    success_rate_pct: float


class SupplierStatOut(BaseModel):
    supplier: str
    total: int
    success_rate_pct: float
    avg_seconds: float | None
    manual_count: int
    avg_attempts: float


class LowStockOut(BaseModel):
    sku_code: str
    available: int


class CostChangeOut(BaseModel):
    sku_code: str
    supplier_slug: str
    cost_usdt: Decimal
    previous_cost_usdt: Decimal | None
    captured_at: datetime


class OpsAnalyticsOut(BaseModel):
    generated_at: datetime
    range: AnalyticsRange
    payments: list[ProviderStatOut]
    stuck_pending: int
    webhook_unhealthy: int
    fulfillment: list[SupplierStatOut]
    stuck_tasks: int
    low_stock: list[LowStockOut]
    expiring_soon: int
    supplier_cost: list[CostChangeOut]


__all__ = [
    "AnalyticsRange",
    "BrandRevenueOut",
    "BusinessAnalyticsOut",
    "BusinessSummaryOut",
    "CostChangeOut",
    "CurrencyAmount",
    "CustomersOut",
    "DashboardOut",
    "DayBucket",
    "FunnelOut",
    "InventorySummary",
    "LocaleCountOut",
    "LowStockOut",
    "NewUsersPoint",
    "OpsAnalyticsOut",
    "ProviderStatOut",
    "RevenuePoint",
    "SkuRevenueOut",
    "StatusCount",
    "SupplierStatOut",
    "range_to_days",
]
