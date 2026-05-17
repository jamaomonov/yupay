"""Public surface of the ``stats`` module."""

from yupay.modules.stats.routes import admin_router
from yupay.modules.stats.schemas import (
    CurrencyAmount,
    DashboardOut,
    DayBucket,
    InventorySummary,
    StatusCount,
)
from yupay.modules.stats.service import build_dashboard

__all__ = [
    "CurrencyAmount",
    "DashboardOut",
    "DayBucket",
    "InventorySummary",
    "StatusCount",
    "admin_router",
    "build_dashboard",
]
