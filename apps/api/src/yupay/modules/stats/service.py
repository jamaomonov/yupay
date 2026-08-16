"""Dashboard aggregate service.

All queries hit indexes (``created_at`` on every event table). For the
skeleton's volumes one Dashboard request fires ~8 SELECTs, none of which
scans more than a day's worth of rows. Move to a materialised rollup when
``orders`` crosses ~1M rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.inventory.models import InventoryCode
from yupay.modules.orders.models import Order
from yupay.modules.orders.revenue import order_charged_usd_subq
from yupay.modules.payments.models import Payment
from yupay.modules.stats.schemas import (
    CurrencyAmount,
    DashboardOut,
    DayBucket,
    InventorySummary,
    StatusCount,
)

# Window: last N hours for the headline KPIs.
_DEFAULT_WINDOW_HOURS = 24
_STUCK_PAYMENT_AFTER = timedelta(hours=1)
_PENDING_ORDER_AFTER = timedelta(minutes=5)
_LOW_STOCK_THRESHOLD = 10


async def build_dashboard(
    db: AsyncSession, *, window_hours: int = _DEFAULT_WINDOW_HOURS
) -> DashboardOut:
    """Build the dashboard payload in one shot."""
    moment = now()
    window_start = moment - timedelta(hours=window_hours)

    orders_in_window = await _count_orders_in_window(db, window_start)
    orders_delivered = await _count_orders_with_status_in_window(
        db, window_start, statuses=("delivered",)
    )
    orders_failed = await _count_orders_with_status_in_window(
        db, window_start, statuses=("cancelled", "expired")
    )

    revenue = await _revenue_in_window(db, window_start)
    status_mix = await _status_breakdown(db, window_start)

    in_flight = await _count_in_flight_tasks(db)
    stuck = await _count_stuck_payments(db, moment - _STUCK_PAYMENT_AFTER)
    pending = await _count_pending_orders(db, moment - _PENDING_ORDER_AFTER)

    inventory = await _inventory_summary(db)
    last_7 = await _orders_last_7_days(db, moment)

    return DashboardOut(
        generated_at=moment,
        window_hours=window_hours,
        orders_in_window=orders_in_window,
        orders_delivered_in_window=orders_delivered,
        orders_failed_in_window=orders_failed,
        revenue_in_window=revenue,
        status_breakdown=status_mix,
        in_flight_tasks=in_flight,
        stuck_payments=stuck,
        pending_orders=pending,
        inventory=inventory,
        orders_last_7_days=last_7,
    )


# ---------- helpers ---------------------------------------------------------


async def _count_orders_in_window(db: AsyncSession, since: datetime) -> int:
    stmt = select(func.count()).select_from(Order).where(Order.created_at >= since)
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _count_orders_with_status_in_window(
    db: AsyncSession, since: datetime, *, statuses: tuple[str, ...]
) -> int:
    stmt = (
        select(func.count())
        .select_from(Order)
        .where(Order.created_at >= since, Order.status.in_(statuses))
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _revenue_in_window(db: AsyncSession, since: datetime) -> list[CurrencyAmount]:
    """Sum of ``total_charged`` per currency for orders that actually generated
    money in the window. We count anything past ``paid`` — refunds are not
    netted out here because the dashboard shows gross revenue."""
    paid_like = ("paid", "fulfilling", "fulfilled", "delivered")
    stmt = (
        select(Order.currency, func.sum(Order.total_charged))
        .where(Order.created_at >= since, Order.status.in_(paid_like))
        .group_by(Order.currency)
    )
    rows = (await db.execute(stmt)).all()
    return [CurrencyAmount(currency=cur, amount=Decimal(str(amt or 0))) for cur, amt in rows]


async def _status_breakdown(db: AsyncSession, since: datetime) -> list[StatusCount]:
    stmt = (
        select(Order.status, func.count())
        .where(Order.created_at >= since)
        .group_by(Order.status)
        .order_by(func.count().desc())
    )
    rows = (await db.execute(stmt)).all()
    return [StatusCount(status=s, count=int(c)) for s, c in rows]


async def _count_in_flight_tasks(db: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(FulfillmentTask)
        .where(FulfillmentTask.status.in_(("pending", "in_progress")))
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _count_stuck_payments(db: AsyncSession, older_than: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(Payment)
        .where(Payment.status == "pending", Payment.created_at < older_than)
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _count_pending_orders(db: AsyncSession, older_than: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(Order)
        .where(
            Order.status == "pending_payment",
            Order.created_at < older_than,
        )
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _inventory_summary(db: AsyncSession) -> InventorySummary:
    counts_stmt = select(InventoryCode.state, func.count()).group_by(InventoryCode.state)
    counts = {state: int(c) for state, c in (await db.execute(counts_stmt)).all()}

    # Per-SKU availability — count SKUs whose available-bucket is below threshold.
    sku_stmt = select(
        InventoryCode.sku_id,
        func.sum(
            case(
                (InventoryCode.state == "available", 1),
                else_=0,
            )
        ).label("available_count"),
    ).group_by(InventoryCode.sku_id)
    sku_rows = (await db.execute(sku_stmt)).all()
    low_stock = sum(1 for _sku, available in sku_rows if int(available or 0) < _LOW_STOCK_THRESHOLD)
    return InventorySummary(
        available=counts.get("available", 0),
        reserved=counts.get("reserved", 0),
        issued=counts.get("issued", 0),
        voided=counts.get("voided", 0),
        low_stock_skus=low_stock,
    )


async def _orders_last_7_days(db: AsyncSession, anchor: datetime) -> list[DayBucket]:
    """Day-bucketed orders + revenue for the last 7 days (UTC)."""
    seven_days_ago = anchor - timedelta(days=7)
    day = func.date_trunc("day", Order.created_at)
    # `charged_usd`, not `total_usd` — the latter is a Steam order's face value
    # and undercounts revenue by the whole markup. See `orders.revenue`.
    gross = order_charged_usd_subq()
    stmt = (
        select(
            day.label("d"),
            func.count().label("c"),
            func.sum(gross.c.charged_usd)
            .filter(Order.status.in_(("paid", "fulfilling", "fulfilled", "delivered")))
            .label("rev"),
        )
        .select_from(Order)
        .join(gross, gross.c.order_id == Order.id, isouter=True)
        .where(Order.created_at >= seven_days_ago)
        .group_by(day)
        .order_by(day)
    )
    rows = (await db.execute(stmt)).all()
    # Build a 7-day series with zero-fill for missing days so the sparkline is
    # always a fixed-width array.
    by_date: dict[str, tuple[int, Decimal]] = {}
    for d, c, rev in rows:
        if d is None:
            continue
        iso = d.date().isoformat() if hasattr(d, "date") else str(d)[:10]
        by_date[iso] = (int(c or 0), Decimal(str(rev or 0)))
    out: list[DayBucket] = []
    for i in range(6, -1, -1):
        bucket_date = (anchor - timedelta(days=i)).date().isoformat()
        c, rev = by_date.get(bucket_date, (0, Decimal(0)))
        out.append(DayBucket(date=bucket_date, count=c, revenue_usd=rev))
    return out


# Re-export the analytics builders so existing references keep working. The
# import lives at the bottom of the module so the shared helpers above are
# defined before ``analytics`` imports them (analytics imports service helpers,
# service re-exports analytics builders — the cycle resolves cleanly only in
# this order).
from yupay.modules.stats.analytics import (  # noqa: E402
    build_business_analytics,
    build_ops_analytics,
)

__all__ = ["build_business_analytics", "build_dashboard", "build_ops_analytics"]
