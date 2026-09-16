"""Dashboard aggregate service.

All queries hit indexes (``created_at`` on every event table). For the
skeleton's volumes one Dashboard request fires ~11 SELECTs, none of which
scans more than two days' worth of rows — the window and the one before it,
which is what makes every headline a movement instead of an absolute. Move to a materialised rollup when
``orders`` crosses ~1M rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.modules.catalog.models import Sku
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.inventory.models import InventoryCode
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.orders.revenue import (
    charged_usd_expr,
    margin_usd_expr,
    order_charged_usd_subq,
)
from yupay.modules.orders.scope import IS_SALE
from yupay.modules.payments.models import Payment
from yupay.modules.stats._time import local_date_of, local_day
from yupay.modules.stats.schemas import (
    CurrencyAmount,
    DashboardChannel,
    DashboardMargin,
    DashboardOut,
    DashboardTotals,
    DayBucket,
    InventorySummary,
    StatusCount,
)

# Window: last N hours for the headline KPIs.
_DEFAULT_WINDOW_HOURS = 24
_STUCK_PAYMENT_AFTER = timedelta(hours=1)
_PENDING_ORDER_AFTER = timedelta(minutes=5)
_LOW_STOCK_THRESHOLD = 10
#: Statuses that count as "this order produced money". Shared by the revenue
#: and margin queries on purpose: the two sit side by side on the card, so a
#: figure either appears in both or in neither.
_PAID_LIKE = ("paid", "fulfilling", "fulfilled", "delivered")


async def build_dashboard(
    db: AsyncSession, *, window_hours: int = _DEFAULT_WINDOW_HOURS
) -> DashboardOut:
    """Build the dashboard payload in one shot."""
    moment = now()
    span = timedelta(hours=window_hours)
    window_start = moment - span

    margin = await _margin_in_window(db, window_start)
    totals = await _window_totals(db, window_start, moment, margin=margin)
    # The window of equal length immediately before, so the cards can show a
    # movement rather than an absolute. Derived from this window rather than
    # configured: a 24-hour figure must never be held up against a week.
    earlier_margin = await _margin_in_window(db, window_start - span, until=window_start)
    previous = await _window_totals(db, window_start - span, window_start, margin=earlier_margin)

    revenue = await _revenue_in_window(db, window_start)
    status_mix = await _status_breakdown(db, window_start)
    channels = await _channels_in_window(db, window_start)

    in_flight = await _count_in_flight_tasks(db)
    stuck = await _count_stuck_payments(db, moment - _STUCK_PAYMENT_AFTER)
    pending = await _count_pending_orders(db, moment - _PENDING_ORDER_AFTER)

    inventory = await _inventory_summary(db)
    last_7 = await _orders_last_7_days(db, moment)

    return DashboardOut(
        generated_at=moment,
        window_hours=window_hours,
        # The same numbers as `totals`, kept flat because the admin bundle
        # ships separately from the API and an older one still reads them.
        orders_in_window=totals.orders,
        orders_delivered_in_window=totals.delivered,
        orders_failed_in_window=totals.failed,
        revenue_in_window=revenue,
        margin_in_window=margin,
        status_breakdown=status_mix,
        in_flight_tasks=in_flight,
        stuck_payments=stuck,
        pending_orders=pending,
        inventory=inventory,
        orders_last_7_days=last_7,
        totals=totals,
        previous=_meaningful(previous),
        channels_in_window=channels,
    )


def _meaningful(totals: DashboardTotals) -> DashboardTotals | None:
    """`None` for a window in which nothing happened at all.

    A shop's first day has no yesterday, and "+100% against zero" is a worse
    answer than no chip at all.
    """
    return None if totals.orders == 0 and totals.revenue_usd == 0 else totals


# ---------- helpers ---------------------------------------------------------


async def _window_totals(
    db: AsyncSession, since: datetime, until: datetime, *, margin: DashboardMargin
) -> DashboardTotals:
    """The six comparable figures for one window, in two queries.

    Was three separate `COUNT` queries that differed only by a status filter;
    aggregate filters collapse them into one, which matters because this now
    runs twice per request — once for the window and once for the one before.

    Money is `charged_usd`, never `Order.total_usd`: on a variable-amount line
    the latter is the face value the customer picked, so the markup — the
    margin the business runs on — would be missing from revenue while still
    being counted as margin on the card beside it. See `orders.revenue`.

    Windowed on `created_at` throughout, like everything else on this screen:
    the dashboard answers "what happened in the last 24 hours", not "what
    settled in them".
    """
    counts_stmt = select(
        func.count(),
        func.count().filter(Order.status == "delivered"),
        func.count().filter(Order.status.in_(("cancelled", "expired"))),
    ).where(IS_SALE, Order.created_at >= since, Order.created_at < until)
    orders_raw, delivered_raw, failed_raw = (await db.execute(counts_stmt)).one()

    gross = order_charged_usd_subq()
    money_stmt = (
        select(
            func.coalesce(func.sum(gross.c.charged_usd).filter(Order.status.in_(_PAID_LIKE)), 0),
            func.coalesce(func.sum(gross.c.charged_usd).filter(Order.status == "refunded"), 0),
        )
        .select_from(Order)
        .join(gross, gross.c.order_id == Order.id, isouter=True)
        .where(IS_SALE, Order.created_at >= since, Order.created_at < until)
    )
    revenue_raw, refunded_raw = (await db.execute(money_stmt)).one()

    return DashboardTotals(
        orders=int(orders_raw or 0),
        delivered=int(delivered_raw or 0),
        failed=int(failed_raw or 0),
        revenue_usd=Decimal(str(revenue_raw or 0)).quantize(Decimal("0.01")),
        margin_usd=margin.amount_usd,
        refunded_usd=Decimal(str(refunded_raw or 0)).quantize(Decimal("0.01")),
    )


async def _channels_in_window(db: AsyncSession, since: datetime) -> list[DashboardChannel]:
    """Retail and B2B, side by side.

    A reseller's order and a customer's are one tally otherwise, and the
    number that moves is the one nobody can see. Both rows are always emitted,
    including at zero: a missing row reads as missing data rather than as a
    quiet morning on that side.
    """
    gross = order_charged_usd_subq()
    is_b2b = Order.merchant_id.isnot(None)
    stmt = (
        select(
            is_b2b.label("b2b"),
            func.count(),
            func.coalesce(func.sum(gross.c.charged_usd).filter(Order.status.in_(_PAID_LIKE)), 0),
        )
        .select_from(Order)
        .join(gross, gross.c.order_id == Order.id, isouter=True)
        .where(IS_SALE, Order.created_at >= since)
        .group_by(is_b2b)
    )
    seen = {
        ("b2b" if b2b else "retail"): (int(count or 0), Decimal(str(revenue or 0)))
        for b2b, count, revenue in (await db.execute(stmt)).all()
    }
    return [
        DashboardChannel(
            channel=name,
            orders=seen.get(name, (0, Decimal(0)))[0],
            revenue_usd=seen.get(name, (0, Decimal(0)))[1].quantize(Decimal("0.01")),
        )
        for name in ("retail", "b2b")
    ]


async def _revenue_in_window(db: AsyncSession, since: datetime) -> list[CurrencyAmount]:
    """Sum of ``total_charged`` per currency for orders that actually generated
    money in the window. We count anything past ``paid`` — refunds are not
    netted out here because the dashboard shows gross revenue."""
    stmt = (
        select(Order.currency, func.sum(Order.total_charged))
        .where(IS_SALE, Order.created_at >= since, Order.status.in_(_PAID_LIKE))
        .group_by(Order.currency)
    )
    rows = (await db.execute(stmt)).all()
    return [CurrencyAmount(currency=cur, amount=Decimal(str(amt or 0))) for cur, amt in rows]


async def _margin_in_window(
    db: AsyncSession, since: datetime, *, until: datetime | None = None
) -> DashboardMargin:
    """What the window's revenue actually left us, in USD.

    Deliberately the same orders as :func:`_revenue_in_window` — same window,
    same statuses, same ``IS_SALE`` — because the two render side by side. A
    margin scoped even slightly differently from the revenue beside it is worse
    than no margin at all: it invites a comparison that does not hold.

    USD rather than the charged currency: cost is recorded in USD on the SKU,
    so a per-currency margin would need an FX rate to exist at all, and which
    rate (today's? the order's?) is a question the card cannot answer. The
    percentage is the figure that survives the currency mismatch, which is why
    it is here rather than left to the reader.

    ``unknown_units`` are units whose SKU has no recorded cost. They are absent
    from both the margin and the gross it is a percentage of — counting them at
    zero cost would report an unknown as a 100% margin — so the card can say
    the number is partial instead of implying it is complete.

    ``until`` closes the window at the top, which the current one does not
    need — it runs to now — and the comparison window does: without it the
    "previous 24 hours" would quietly include the present ones.
    """
    priced = select(
        func.coalesce(func.sum(charged_usd_expr()).filter(margin_usd_expr().isnot(None)), 0),
        func.coalesce(func.sum(margin_usd_expr()), 0),
        func.coalesce(func.sum(OrderItem.qty).filter(margin_usd_expr().is_(None)), 0),
    ).select_from(OrderItem)
    stmt = (
        priced.join(Order, Order.id == OrderItem.order_id)
        .join(Sku, Sku.id == OrderItem.sku_id)
        .where(IS_SALE, Order.created_at >= since, Order.status.in_(_PAID_LIKE))
    )
    if until is not None:
        stmt = stmt.where(Order.created_at < until)
    gross_raw, margin_raw, unknown_raw = (await db.execute(stmt)).one()
    gross = Decimal(str(gross_raw or 0))
    margin = Decimal(str(margin_raw or 0))
    pct = float(margin / gross * 100) if gross > 0 else 0.0
    return DashboardMargin(
        amount_usd=margin.quantize(Decimal("0.01")),
        pct=round(pct, 2),
        unknown_units=int(unknown_raw or 0),
    )


async def _status_breakdown(db: AsyncSession, since: datetime) -> list[StatusCount]:
    stmt = (
        select(Order.status, func.count())
        .where(IS_SALE, Order.created_at >= since)
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
            IS_SALE,
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
    """Day-bucketed orders + revenue for the last 7 days, on the local clock.

    Buckets and zero-fill keys have to move together: the fill builds the fixed
    seven-slot array by date string, so grouping locally while filling from UTC
    dates would miss every bucket and draw a flat empty sparkline. Both go
    through ``stats._time`` for that reason.
    """
    seven_days_ago = anchor - timedelta(days=7)
    day = local_day(Order.created_at)
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
        .where(IS_SALE, Order.created_at >= seven_days_ago)
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
        bucket_date = local_date_of(anchor - timedelta(days=i))
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
