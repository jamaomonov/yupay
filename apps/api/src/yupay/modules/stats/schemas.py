"""Pydantic DTOs for the admin Dashboard payload."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

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


class DashboardMargin(BaseModel):
    """What the window's revenue left us, beside the revenue itself.

    USD-only by necessity: cost is recorded in USD on the SKU, while revenue is
    charged per currency. ``pct`` is what makes the two comparable on one card.
    """

    model_config = ConfigDict(extra="forbid")

    amount_usd: Decimal
    pct: float
    #: Units sold whose SKU has no recorded cost. Excluded from both figures
    #: above, so a non-zero value means they describe part of the window's
    #: sales, not all of it.
    unknown_units: int


class DashboardTotals(BaseModel):
    """The window's figures, in a shape another window can be compared against.

    Every headline on the dashboard used to be an absolute, and "43 заказа" is
    neither good nor bad without the number it replaced. So the same six
    figures are emitted for the current window and for the one of equal length
    immediately before it, and the card does the subtraction.

    ``revenue_usd`` exists beside the per-currency ``revenue_in_window`` for
    exactly that reason: a list of three currencies cannot be compared with
    another list of three currencies, and a delta needs one number.
    """

    model_config = ConfigDict(extra="forbid")

    orders: int
    delivered: int
    #: Cancelled or expired — the two ways an order dies without a refund.
    failed: int
    #: Summed from ``charged_usd``, never ``total_usd``: see ``orders.revenue``.
    revenue_usd: Decimal
    margin_usd: Decimal
    #: Money given back. Gross revenue above does not net it out, so without
    #: this the screen cannot say a good day was undone by an afternoon of
    #: refunds.
    refunded_usd: Decimal


class DashboardChannel(BaseModel):
    """One side of the business over the window.

    Retail and B2B are one blended tally on this screen otherwise, and "43
    orders" does not say whether the wholesale side moved at all.
    ``Order.merchant_id`` is the entire distinction.
    """

    model_config = ConfigDict(extra="forbid")

    #: ``"retail"`` or ``"b2b"``.
    channel: str
    orders: int
    revenue_usd: Decimal


class DashboardOut(BaseModel):
    """Single payload behind ``GET /admin/stats/dashboard``."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    window_hours: int

    orders_in_window: int
    orders_delivered_in_window: int
    orders_failed_in_window: int

    revenue_in_window: list[CurrencyAmount]
    margin_in_window: DashboardMargin
    status_breakdown: list[StatusCount]

    in_flight_tasks: int
    stuck_payments: int  # pending payments older than 1 hour
    pending_orders: int  # pending_payment older than 5 minutes

    inventory: InventorySummary

    orders_last_7_days: list[DayBucket]

    #: The same six figures the card compares. The flat fields above are the
    #: same numbers, kept because the admin bundle ships separately from the
    #: API and an older one still reads them.
    totals: DashboardTotals
    #: The window of equal length immediately before this one. ``None`` when
    #: nothing at all happened in it — an honest blank rather than a "+100%"
    #: against zero.
    previous: DashboardTotals | None = None
    channels_in_window: list[DashboardChannel] = []


class AnalyticsChannel(StrEnum):
    """Which half of the business a figure is about.

    Retail and B2B have genuinely different economics — a reseller buys at a
    wholesale price with a thinner markup — so a blended margin flatters one
    and libels the other. Every figure on the business tab can be scoped to
    one of them, or left across both.
    """

    ALL = "all"
    RETAIL = "retail"
    B2B = "b2b"


class AnalyticsRange(StrEnum):
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
    #: Approximate, on the same basis as the summary's: fixed SKUs with a known
    #: cost and variable ones priced off a multiplier. ``None`` when nothing
    #: that day had a cost we know, which is not the same as a zero margin.
    margin_usd: Decimal | None = None
    #: Units that day whose cost we do not know, so a reader can tell a thin
    #: margin from an incomplete one.
    margin_unknown_units: int = 0


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


class ChannelStatOut(BaseModel):
    """Retail versus B2B. Wholesale margin is a different number entirely."""

    channel: str
    gmv_usd: Decimal
    orders: int
    margin_usd: Decimal | None


class HourPoint(BaseModel):
    """Orders by hour of the local day — staffing and supplier windows."""

    hour: int
    orders: int
    revenue_usd: Decimal


class BusinessSummaryOut(BaseModel):
    gmv_usd: Decimal
    orders: int
    paid_orders: int
    delivered_orders: int
    aov_usd: Decimal
    gross_margin_usd: Decimal
    margin_pct: float
    margin_approx: bool
    margin_unknown_units: int
    #: Money given back in the window. The funnel counts refunds in orders;
    #: this is what they cost.
    refunded_usd: Decimal = Decimal("0")


class CustomersOut(BaseModel):
    new_users_series: list[NewUsersPoint]
    guest_orders: int
    registered_orders: int
    repeat_rate_pct: float
    top_locales: list[LocaleCountOut]


class BusinessAnalyticsOut(BaseModel):
    generated_at: datetime
    #: ``None`` for an explicit ``since``/``until`` window, which is every
    #: request the calendar makes.
    range: AnalyticsRange | None = None
    channel: AnalyticsChannel = AnalyticsChannel.ALL
    since: datetime | None = None
    #: Exclusive. ``None`` means the window runs up to ``generated_at``.
    until: datetime | None = None
    summary: BusinessSummaryOut
    revenue_series: list[RevenuePoint]
    funnel: FunnelOut
    top_brands: list[BrandRevenueOut]
    top_skus: list[SkuRevenueOut]
    customers: CustomersOut
    #: The window of the same length immediately before this one, so every
    #: headline can be read as a movement rather than an absolute. ``None``
    #: when there is no earlier data to compare against.
    previous: BusinessSummaryOut | None = None
    channels: list[ChannelStatOut] = []
    hourly: list[HourPoint] = []


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


class WalletLiabilityOut(BaseModel):
    """Customer money we are holding, per currency. Ours to return, not to spend."""

    currency: str
    amount: Decimal


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
    #: A balance, not a period figure: how much customer money sits in wallets
    #: right now. It is a liability — spendable by them, not by us.
    wallet_liability: list[WalletLiabilityOut] = []


__all__ = [
    "AnalyticsChannel",
    "AnalyticsRange",
    "BrandRevenueOut",
    "BusinessAnalyticsOut",
    "BusinessSummaryOut",
    "ChannelStatOut",
    "CostChangeOut",
    "CurrencyAmount",
    "CustomersOut",
    "DashboardOut",
    "DayBucket",
    "FunnelOut",
    "HourPoint",
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
    "WalletLiabilityOut",
    "range_to_days",
]
