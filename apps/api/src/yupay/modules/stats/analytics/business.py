"""Business tab analytics: revenue, margin (approx), funnel, product mix, customers."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Case, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.orders.revenue import order_charged_usd_subq
from yupay.modules.stats.analytics._common import _PAID_LIKE
from yupay.modules.stats.schemas import (
    AnalyticsRange,
    BrandRevenueOut,
    BusinessAnalyticsOut,
    BusinessSummaryOut,
    CustomersOut,
    FunnelOut,
    LocaleCountOut,
    NewUsersPoint,
    RevenuePoint,
    SkuRevenueOut,
    range_to_days,
)
from yupay.modules.users.models import User


def _margin_expr() -> Case[Any]:
    """Per-order-item margin (USD), for use inside ``func.sum(...)``.

    Fixed SKUs with a known cost: ``qty * (unit_price_usd - cost_usdt)``.
    Variable-amount (Steam) SKUs: ``unit_price_usd`` is the raw dollar cost
    basis and ``rate_multiplier`` is the SKU's markup (always set for
    variable SKUs — see ``ck_skus_variable_amount_complete``), so margin is
    ``qty * unit_price_usd * (rate_multiplier - 1)``. See
    ``docs/superpowers/specs/2026-08-04-steam-margin-analytics-design.md``.

    Fixed SKUs without a known cost evaluate to ``NULL``, so
    ``func.sum(_margin_expr())`` naturally excludes them from a group's
    total (NULL when a group has no costable rows at all).

    Twin of ``orders.revenue.charged_usd_expr`` — that one is the gross, this
    one the part of it we keep, and ``gross - margin == cost``. Change the
    treatment of a SKU kind in one and it has to change in the other.

    Returns:
        A SQLAlchemy ``CASE`` expression. Typed ``Case[Any]`` because
        SQLAlchemy's ``case()`` stub always returns ``Case[Any]``,
        regardless of the branch value types.
    """
    return case(
        (
            Sku.variable_amount.is_(True),
            OrderItem.qty * OrderItem.unit_price_usd * (Sku.rate_multiplier - 1),
        ),
        (
            Sku.cost_usdt.isnot(None),
            OrderItem.qty * (OrderItem.unit_price_usd - Sku.cost_usdt),
        ),
        else_=None,
    )


async def build_business_analytics(db: AsyncSession, *, r: AnalyticsRange) -> BusinessAnalyticsOut:
    """Business tab: revenue, margin (approx), funnel, product mix, customers."""
    moment = now()
    since = moment - timedelta(days=range_to_days(r))

    # The KPI card ("Заказов" / "оплачено N") and the funnel below it must never
    # disagree, so both are built from the *same* created_at-windowed status
    # counts — one query, two consumers. See ``_funnel`` and ``_business_summary``.
    status_counts = await _status_counts_since(db, since)
    funnel = _funnel(status_counts)
    summary = await _business_summary(db, since, status_counts)
    revenue_series = await _revenue_series(db, since)
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


async def _business_summary(
    db: AsyncSession, since: datetime, status_counts: dict[str, int]
) -> BusinessSummaryOut:
    # GMV: money actually collected in the window — orders whose *payment*
    # landed in ``since..now`` (``paid_at``-windowed), which can include orders
    # created just before the window started. This is a deliberately different
    # population from the created_at-windowed counts below; it only feeds
    # revenue/margin/AOV, never the "orders" / "paid_orders" headline counts
    # (those come from ``status_counts`` so they match the funnel exactly).
    # Summed from `charged_usd`, not `Order.total_usd`: on a variable-amount
    # line the latter is the face value the customer picked, so GMV would
    # exclude the markup — the very thing the margin block below counts as
    # ours. See `orders.revenue`.
    gross = order_charged_usd_subq()
    gmv_raw = (
        await db.execute(
            select(func.coalesce(func.sum(gross.c.charged_usd), 0))
            .select_from(Order)
            .join(gross, gross.c.order_id == Order.id, isouter=True)
            .where(Order.paid_at >= since, Order.status.in_(_PAID_LIKE))
        )
    ).scalar_one()
    gmv = Decimal(str(gmv_raw or 0))

    # Orders / paid / delivered counts share the funnel's created_at-windowed
    # status counts — see ``build_business_analytics``. "Paid" here means
    # "reached paid or beyond" (paid/fulfilling/fulfilled/delivered all count),
    # same rule as the funnel's ``paid`` bucket.
    total_created = sum(status_counts.values())
    paid_orders = sum(status_counts.get(s, 0) for s in _PAID_LIKE)
    delivered_orders = status_counts.get("delivered", 0)

    # Margin (approx): join items→sku, split fixed-known-cost / variable
    # (Steam, priced off rate_multiplier) / unknown (fixed, cost_usdt NULL).
    # See ``_margin_expr`` and the design doc referenced there.
    m = (
        select(
            func.coalesce(
                func.sum(OrderItem.qty * OrderItem.unit_price_usd).filter(
                    Sku.variable_amount.is_(False), Sku.cost_usdt.isnot(None)
                ),
                0,
            )
            + func.coalesce(
                func.sum(OrderItem.qty * OrderItem.unit_price_usd * Sku.rate_multiplier).filter(
                    Sku.variable_amount.is_(True)
                ),
                0,
            ),
            func.coalesce(
                func.sum(OrderItem.qty * Sku.cost_usdt).filter(
                    Sku.variable_amount.is_(False), Sku.cost_usdt.isnot(None)
                ),
                0,
            )
            + func.coalesce(
                func.sum(OrderItem.qty * OrderItem.unit_price_usd).filter(
                    Sku.variable_amount.is_(True)
                ),
                0,
            ),
            func.coalesce(
                func.sum(OrderItem.qty).filter(
                    Sku.variable_amount.is_(False), Sku.cost_usdt.is_(None)
                ),
                0,
            ),
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
        delivered_orders=delivered_orders,
        aov_usd=aov.quantize(Decimal("0.01")) if paid_orders else Decimal("0"),
        gross_margin_usd=margin,
        margin_pct=round(margin_pct, 2),
        margin_approx=True,
        margin_unknown_units=int(unknown_units or 0),
    )


async def _revenue_series(db: AsyncSession, since: datetime) -> list[RevenuePoint]:
    day = func.date_trunc("day", Order.paid_at)
    # Same basis as the GMV headline — the two must not disagree.
    gross = order_charged_usd_subq()
    stmt = (
        select(
            day.label("d"),
            func.coalesce(func.sum(gross.c.charged_usd), 0).label("rev"),
            func.count(Order.id).label("c"),
        )
        .select_from(Order)
        .join(gross, gross.c.order_id == Order.id, isouter=True)
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


async def _status_counts_since(db: AsyncSession, since: datetime) -> dict[str, int]:
    """Order counts by current status, for orders *created* since ``since``.

    Single source of truth for both the funnel and the "orders" / "paid
    orders" / "delivered orders" KPI headlines — see ``build_business_analytics``.
    """
    stmt = (
        select(Order.status, func.count()).where(Order.created_at >= since).group_by(Order.status)
    )
    return {s: int(c) for s, c in (await db.execute(stmt)).all()}


def _funnel(counts: dict[str, int]) -> FunnelOut:
    """Build the funnel from status counts.

    Each stage is *cumulative* — "reached this stage or beyond" — so the
    funnel is monotonically non-increasing (``delivered <= fulfilling <=
    paid <= created``) instead of counting only orders currently sitting in
    that exact status. Without this, an order that already progressed from
    ``paid`` to ``delivered`` would vanish from the "paid" bucket entirely,
    which previously produced nonsense like "Оплачено 0, Доставлено 6".
    """
    created = sum(counts.values())
    paid = sum(counts.get(s, 0) for s in _PAID_LIKE)
    fulfilling_or_beyond = (
        counts.get("fulfilling", 0) + counts.get("fulfilled", 0) + counts.get("delivered", 0)
    )
    delivered = counts.get("delivered", 0)
    conv = (paid / created * 100) if created else 0.0
    return FunnelOut(
        created=created,
        paid=paid,
        fulfilling=fulfilling_or_beyond,
        delivered=delivered,
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
            # Margin (fixed known-cost + variable/Steam) — NULL when the group
            # has no costable rows. See ``_margin_expr``.
            func.sum(_margin_expr()),
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
            # Margin (fixed known-cost + variable/Steam) — NULL when the group
            # has no costable rows. See ``_margin_expr``.
            func.sum(_margin_expr()),
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


__all__ = ["build_business_analytics"]
