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
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.inventory.models import InventoryCode
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.payments.models import Payment
from yupay.modules.stats.schemas import (
    AnalyticsRange,
    BrandRevenueOut,
    BusinessAnalyticsOut,
    BusinessSummaryOut,
    CurrencyAmount,
    CustomersOut,
    DashboardOut,
    DayBucket,
    FunnelOut,
    InventorySummary,
    LocaleCountOut,
    NewUsersPoint,
    RevenuePoint,
    SkuRevenueOut,
    StatusCount,
    range_to_days,
)
from yupay.modules.users.models import User

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
    stmt = (
        select(
            day.label("d"),
            func.count().label("c"),
            func.sum(Order.total_usd)
            .filter(Order.status.in_(("paid", "fulfilling", "fulfilled", "delivered")))
            .label("rev"),
        )
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


_PAID_LIKE = ("paid", "fulfilling", "fulfilled", "delivered")


async def build_business_analytics(db: AsyncSession, *, r: AnalyticsRange) -> BusinessAnalyticsOut:
    """Business tab: revenue, margin (approx), funnel, product mix, customers."""
    moment = now()
    since = moment - timedelta(days=range_to_days(r))

    summary = await _business_summary(db, since)
    revenue_series = await _revenue_series(db, since)
    funnel = await _funnel(db, since)
    top_brands = await _top_brands(db, since)
    top_skus = await _top_skus(db, since)
    customers = await _customers(db, since)

    return BusinessAnalyticsOut(
        generated_at=moment,
        range=r,
        summary=summary,
        revenue_series=revenue_series,
        funnel=funnel,
        top_brands=top_brands,
        top_skus=top_skus,
        customers=customers,
    )


async def _business_summary(db: AsyncSession, since: datetime) -> BusinessSummaryOut:
    # Orders + GMV + FX P&L over paid-like orders paid in window.
    base = select(
        func.count(Order.id),
        func.coalesce(func.sum(Order.total_usd), 0),
        func.coalesce(func.sum(Order.total_charged - Order.total_usd), 0),
        func.count(Order.id).filter(Order.status == "delivered"),
    ).where(Order.paid_at >= since, Order.status.in_(_PAID_LIKE))
    paid_orders_row, gmv_raw, fx_pnl_raw, delivered_raw = (await db.execute(base)).one()
    paid_orders = int(paid_orders_row or 0)
    gmv = Decimal(str(gmv_raw or 0))

    # Total orders created (for "orders" headline) in same window by created_at.
    total_created = int(
        (
            await db.execute(select(func.count(Order.id)).where(Order.created_at >= since))
        ).scalar_one()
        or 0
    )

    # Margin (approx): join items→sku, only rows with cost_usdt known.
    m = (
        select(
            func.coalesce(
                func.sum(OrderItem.qty * OrderItem.unit_price_usd).filter(
                    Sku.cost_usdt.isnot(None)
                ),
                0,
            ),
            func.coalesce(
                func.sum(OrderItem.qty * Sku.cost_usdt).filter(Sku.cost_usdt.isnot(None)), 0
            ),
            func.coalesce(func.sum(OrderItem.qty).filter(Sku.cost_usdt.is_(None)), 0),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Sku, Sku.id == OrderItem.sku_id)
        .where(Order.paid_at >= since, Order.status.in_(_PAID_LIKE))
    )
    known_rev_raw, known_cost_raw, unknown_units = (await db.execute(m)).one()
    known_rev = Decimal(str(known_rev_raw or 0))
    known_cost = Decimal(str(known_cost_raw or 0))
    margin = known_rev - known_cost
    margin_pct = float(margin / known_rev * 100) if known_rev > 0 else 0.0
    aov = (gmv / paid_orders) if paid_orders else Decimal("0")

    return BusinessSummaryOut(
        gmv_usd=gmv,
        orders=total_created,
        paid_orders=paid_orders,
        delivered_orders=int(delivered_raw or 0),
        aov_usd=aov.quantize(Decimal("0.01")) if paid_orders else Decimal("0"),
        fx_pnl_usd=Decimal(str(fx_pnl_raw or 0)),
        gross_margin_usd=margin,
        margin_pct=round(margin_pct, 2),
        margin_approx=True,
        margin_unknown_units=int(unknown_units or 0),
    )


async def _revenue_series(db: AsyncSession, since: datetime) -> list[RevenuePoint]:
    day = func.date_trunc("day", Order.paid_at)
    stmt = (
        select(
            day.label("d"),
            func.coalesce(func.sum(Order.total_usd), 0).label("rev"),
            func.count(Order.id).label("c"),
        )
        .where(Order.paid_at >= since, Order.status.in_(_PAID_LIKE))
        .group_by(day)
        .order_by(day)
    )
    rows = (await db.execute(stmt)).all()
    return [
        RevenuePoint(
            date=d.date() if hasattr(d, "date") else d,
            revenue_usd=Decimal(str(rev or 0)),
            orders=int(c or 0),
        )
        for d, rev, c in rows
        if d is not None
    ]


async def _funnel(db: AsyncSession, since: datetime) -> FunnelOut:
    stmt = (
        select(Order.status, func.count())
        .where(Order.created_at >= since)
        .group_by(Order.status)
    )
    counts = {s: int(c) for s, c in (await db.execute(stmt)).all()}
    created = sum(counts.values())
    paid = sum(counts.get(s, 0) for s in _PAID_LIKE)
    conv = (paid / created * 100) if created else 0.0
    return FunnelOut(
        created=created,
        paid=counts.get("paid", 0),
        fulfilling=counts.get("fulfilling", 0),
        delivered=counts.get("delivered", 0),
        cancelled=counts.get("cancelled", 0),
        expired=counts.get("expired", 0),
        refunded=counts.get("refunded", 0),
        payment_conversion_pct=round(conv, 2),
    )


async def _top_brands(db: AsyncSession, since: datetime) -> list[BrandRevenueOut]:
    stmt = (
        select(
            Brand.slug,
            func.coalesce(func.sum(OrderItem.qty * OrderItem.unit_price_usd), 0),
            func.coalesce(func.sum(OrderItem.qty), 0),
            func.coalesce(
                func.sum(OrderItem.qty * Sku.cost_usdt).filter(Sku.cost_usdt.isnot(None)), 0
            ),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Sku, Sku.id == OrderItem.sku_id)
        .join(Product, Product.id == Sku.product_id)
        .join(Brand, Brand.id == Product.brand_id)
        .where(Order.paid_at >= since, Order.status.in_(_PAID_LIKE))
        .group_by(Brand.slug)
        .order_by(func.sum(OrderItem.qty * OrderItem.unit_price_usd).desc())
        .limit(10)
    )
    out: list[BrandRevenueOut] = []
    for slug, rev, units, cost in (await db.execute(stmt)).all():
        rev_d = Decimal(str(rev or 0))
        out.append(
            BrandRevenueOut(
                slug=slug,
                revenue_usd=rev_d,
                units=int(units or 0),
                margin_usd=(rev_d - Decimal(str(cost or 0))),
            )
        )
    return out


async def _top_skus(db: AsyncSession, since: datetime) -> list[SkuRevenueOut]:
    stmt = (
        select(
            Sku.sku_code,
            func.coalesce(func.sum(OrderItem.qty * OrderItem.unit_price_usd), 0),
            func.coalesce(func.sum(OrderItem.qty), 0),
            func.coalesce(
                func.sum(OrderItem.qty * Sku.cost_usdt).filter(Sku.cost_usdt.isnot(None)), 0
            ),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Sku, Sku.id == OrderItem.sku_id)
        .where(Order.paid_at >= since, Order.status.in_(_PAID_LIKE))
        .group_by(Sku.sku_code)
        .order_by(func.sum(OrderItem.qty * OrderItem.unit_price_usd).desc())
        .limit(10)
    )
    out: list[SkuRevenueOut] = []
    for code, rev, units, cost in (await db.execute(stmt)).all():
        rev_d = Decimal(str(rev or 0))
        out.append(
            SkuRevenueOut(
                sku_code=code,
                revenue_usd=rev_d,
                units=int(units or 0),
                margin_usd=(rev_d - Decimal(str(cost or 0))),
            )
        )
    return out


async def _customers(db: AsyncSession, since: datetime) -> CustomersOut:
    day = func.date_trunc("day", User.created_at)
    new_rows = (
        await db.execute(
            select(day.label("d"), func.count())
            .where(User.created_at >= since)
            .group_by(day)
            .order_by(day)
        )
    ).all()
    new_series = [
        NewUsersPoint(date=d.date() if hasattr(d, "date") else d, users=int(c))
        for d, c in new_rows
        if d is not None
    ]

    guest = int(
        (
            await db.execute(
                select(func.count(Order.id)).where(
                    Order.created_at >= since, Order.user_id.is_(None)
                )
            )
        ).scalar_one()
        or 0
    )
    registered = int(
        (
            await db.execute(
                select(func.count(Order.id)).where(
                    Order.created_at >= since, Order.user_id.isnot(None)
                )
            )
        ).scalar_one()
        or 0
    )

    # repeat rate: of distinct users with >=1 order in window, share with >=2.
    per_user = (
        await db.execute(
            select(Order.user_id, func.count(Order.id))
            .where(Order.created_at >= since, Order.user_id.isnot(None))
            .group_by(Order.user_id)
        )
    ).all()
    total_users = len(per_user)
    repeat = sum(1 for _u, c in per_user if int(c) >= 2)
    repeat_pct = round(repeat / total_users * 100, 2) if total_users else 0.0

    locale_rows = (
        await db.execute(
            select(User.locale, func.count())
            .where(User.created_at >= since)
            .group_by(User.locale)
            .order_by(func.count().desc())
            .limit(5)
        )
    ).all()
    locales = [LocaleCountOut(locale=loc or "—", users=int(c)) for loc, c in locale_rows]

    return CustomersOut(
        new_users_series=new_series,
        guest_orders=guest,
        registered_orders=registered,
        repeat_rate_pct=repeat_pct,
        top_locales=locales,
    )


__all__ = ["build_business_analytics", "build_dashboard"]
