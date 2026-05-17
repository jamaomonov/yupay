"""Pydantic DTOs for the admin Dashboard payload."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

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


__all__ = [
    "CurrencyAmount",
    "DashboardOut",
    "DayBucket",
    "InventorySummary",
    "StatusCount",
]
