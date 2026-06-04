"""Analytics aggregate services (business + ops tabs).

Split out of ``service.py`` to keep each file under the size budget. Shares the
dashboard's stuck-payment / low-stock helpers and constants — those stay
canonical in ``service.py`` and are imported here (see bottom of ``service.py``
for the re-export that keeps existing references working).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.integrations.models import SupplierPriceHistory
from yupay.modules.inventory.models import InventoryCode
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.payments.models import Payment, PaymentWebhook
from yupay.modules.stats.schemas import (
    AnalyticsRange,
    BrandRevenueOut,
    BusinessAnalyticsOut,
    BusinessSummaryOut,
    CostChangeOut,
    CustomersOut,
    FunnelOut,
    LocaleCountOut,
    LowStockOut,
    NewUsersPoint,
    OpsAnalyticsOut,
    ProviderStatOut,
    RevenuePoint,
    SkuRevenueOut,
    SupplierStatOut,
    range_to_days,
)
from yupay.modules.stats.service import (
    _LOW_STOCK_THRESHOLD,
    _STUCK_PAYMENT_AFTER,
    _count_stuck_payments,
)
from yupay.modules.users.models import User

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
            # Margin over known-cost rows only — NULL when the group has none.
            func.sum(OrderItem.qty * (OrderItem.unit_price_usd - Sku.cost_usdt)).filter(
                Sku.cost_usdt.isnot(None)
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
    for slug, rev, units, margin in (await db.execute(stmt)).all():
        out.append(
            BrandRevenueOut(
                slug=slug,
                revenue_usd=Decimal(str(rev or 0)),
                units=int(units or 0),
                margin_usd=Decimal(str(margin)) if margin is not None else None,
            )
        )
    return out


async def _top_skus(db: AsyncSession, since: datetime) -> list[SkuRevenueOut]:
    stmt = (
        select(
            Sku.sku_code,
            func.coalesce(func.sum(OrderItem.qty * OrderItem.unit_price_usd), 0),
            func.coalesce(func.sum(OrderItem.qty), 0),
            # Margin over known-cost rows only — NULL when the group has none.
            func.sum(OrderItem.qty * (OrderItem.unit_price_usd - Sku.cost_usdt)).filter(
                Sku.cost_usdt.isnot(None)
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
    for code, rev, units, margin in (await db.execute(stmt)).all():
        out.append(
            SkuRevenueOut(
                sku_code=code,
                revenue_usd=Decimal(str(rev or 0)),
                units=int(units or 0),
                margin_usd=Decimal(str(margin)) if margin is not None else None,
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


async def build_ops_analytics(db: AsyncSession, *, r: AnalyticsRange) -> OpsAnalyticsOut:
    """Ops tab: payments, fulfilment, inventory, supplier cost movements."""
    moment = now()
    since = moment - timedelta(days=range_to_days(r))

    payments = await _payment_stats(db, since)
    stuck_pending = await _count_stuck_payments(db, moment - _STUCK_PAYMENT_AFTER)
    webhook_unhealthy = await _webhook_unhealthy(db, since)
    fulfillment = await _fulfillment_stats(db, since)
    stuck_tasks = await _stuck_tasks(db, moment)
    low_stock = await _low_stock(db)
    expiring_soon = await _expiring_soon(db, moment)
    supplier_cost = await _supplier_cost_changes(db, since)

    return OpsAnalyticsOut(
        generated_at=moment,
        range=r,
        payments=payments,
        stuck_pending=stuck_pending,
        webhook_unhealthy=webhook_unhealthy,
        fulfillment=fulfillment,
        stuck_tasks=stuck_tasks,
        low_stock=low_stock,
        expiring_soon=expiring_soon,
        supplier_cost=supplier_cost,
    )


async def _payment_stats(db: AsyncSession, since: datetime) -> list[ProviderStatOut]:
    stmt = (
        select(
            Payment.provider,
            func.count(),
            func.coalesce(func.sum(Payment.amount).filter(Payment.status == "succeeded"), 0),
            func.count().filter(Payment.status == "succeeded"),
        )
        .where(Payment.created_at >= since)
        .group_by(Payment.provider)
        .order_by(func.count().desc())
    )
    out: list[ProviderStatOut] = []
    for provider, total_raw, vol, ok in (await db.execute(stmt)).all():
        total = int(total_raw or 0)
        rate = round(int(ok or 0) / total * 100, 2) if total else 0.0
        out.append(
            ProviderStatOut(
                provider=provider,
                count=total,
                volume_usd=Decimal(str(vol or 0)),
                success_rate_pct=rate,
            )
        )
    return out


async def _webhook_unhealthy(db: AsyncSession, since: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(PaymentWebhook)
        .where(
            PaymentWebhook.received_at >= since,
            or_(PaymentWebhook.signature_ok.is_(False), PaymentWebhook.processed_at.is_(None)),
        )
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _fulfillment_stats(db: AsyncSession, since: datetime) -> list[SupplierStatOut]:
    secs = func.extract("epoch", FulfillmentTask.succeeded_at - FulfillmentTask.created_at)
    stmt = (
        select(
            FulfillmentTask.supplier,
            func.count(),
            func.count().filter(FulfillmentTask.status == "succeeded"),
            func.avg(secs).filter(FulfillmentTask.status == "succeeded"),
            func.count().filter(FulfillmentTask.completed_by.isnot(None)),
            func.coalesce(func.avg(FulfillmentTask.attempts_count), 0),
        )
        .where(FulfillmentTask.created_at >= since)
        .group_by(FulfillmentTask.supplier)
        .order_by(func.count().desc())
    )
    out: list[SupplierStatOut] = []
    for supplier, total_raw, ok, avg_sec, manual, avg_att in (await db.execute(stmt)).all():
        total = int(total_raw or 0)
        rate = round(int(ok or 0) / total * 100, 2) if total else 0.0
        out.append(
            SupplierStatOut(
                supplier=supplier,
                total=total,
                success_rate_pct=rate,
                avg_seconds=round(float(avg_sec), 1) if avg_sec is not None else None,
                manual_count=int(manual or 0),
                avg_attempts=round(float(avg_att or 0), 2),
            )
        )
    return out


async def _stuck_tasks(db: AsyncSession, moment: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(FulfillmentTask)
        .where(
            FulfillmentTask.status.in_(("pending", "in_progress")),
            FulfillmentTask.next_attempt_at.isnot(None),
            FulfillmentTask.next_attempt_at < moment,
        )
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _low_stock(db: AsyncSession) -> list[LowStockOut]:
    avail = func.sum(case((InventoryCode.state == "available", 1), else_=0)).label("a")
    stmt = (
        select(Sku.sku_code, avail)
        .select_from(InventoryCode)
        .join(Sku, Sku.id == InventoryCode.sku_id)
        .group_by(Sku.sku_code)
        .having(avail < _LOW_STOCK_THRESHOLD)
        .order_by(avail)
        .limit(20)
    )
    return [
        LowStockOut(sku_code=code, available=int(a or 0))
        for code, a in (await db.execute(stmt)).all()
    ]


async def _expiring_soon(db: AsyncSession, moment: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(InventoryCode)
        .where(
            InventoryCode.state == "available",
            InventoryCode.expires_at.isnot(None),
            InventoryCode.expires_at < moment + timedelta(days=7),
        )
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _supplier_cost_changes(db: AsyncSession, since: datetime) -> list[CostChangeOut]:
    stmt = (
        select(
            Sku.sku_code,
            SupplierPriceHistory.supplier_slug,
            SupplierPriceHistory.cost_usdt,
            SupplierPriceHistory.previous_cost_usdt,
            SupplierPriceHistory.captured_at,
        )
        .select_from(SupplierPriceHistory)
        .join(Sku, Sku.id == SupplierPriceHistory.sku_id)
        .where(SupplierPriceHistory.captured_at >= since)
        .order_by(SupplierPriceHistory.captured_at.desc())
        .limit(20)
    )
    return [
        CostChangeOut(
            sku_code=code,
            supplier_slug=slug,
            cost_usdt=Decimal(str(cost)),
            previous_cost_usdt=Decimal(str(prev)) if prev is not None else None,
            captured_at=cap,
        )
        for code, slug, cost, prev, cap in (await db.execute(stmt)).all()
    ]


__all__ = ["build_business_analytics", "build_ops_analytics"]
