"""Business tab analytics: revenue, margin (approx), funnel, product mix, customers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from yupay.core.clock import now
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.orders.revenue import margin_usd_expr, order_charged_usd_subq
from yupay.modules.orders.scope import IS_SALE
from yupay.modules.stats.analytics._common import _PAID_LIKE
from yupay.modules.stats.schemas import (
    AnalyticsChannel,
    AnalyticsRange,
    BrandRevenueOut,
    BusinessAnalyticsOut,
    BusinessSummaryOut,
    ChannelStatOut,
    CustomersOut,
    FunnelOut,
    HourPoint,
    LocaleCountOut,
    NewUsersPoint,
    RevenuePoint,
    SkuRevenueOut,
    range_to_days,
)
from yupay.modules.users.models import User

#: The clock an operator reads. `paid_at` is UTC and Uzbekistan is +5, so an
#: hourly chart built on the raw column puts the evening peak at lunchtime.
_LOCAL_TZ = "Asia/Tashkent"


def _local_day(column: InstrumentedAttribute[datetime | None]) -> ColumnElement[datetime]:
    """``column`` truncated to a day on the clock the business runs on.

    `date_trunc('day', <timestamptz>)` cuts in the *session* timezone, which is
    UTC on prod. That is five hours off the day an operator means, and the
    calendar made the gap visible: a cell said $674.43 for "6 сентября" because
    it was showing the UTC day, while clicking it asked for the Tashkent day and
    got $100.31. Same data, two different 24-hour windows, no way to tell from
    the screen which one you were reading.

    So every day bucket on this tab is cut here, in one place, the same way
    `_hourly` already cut its hours.
    """
    return func.date_trunc("day", func.timezone(_LOCAL_TZ, column))


@dataclass(frozen=True, slots=True)
class Scope:
    """The period every figure on the business tab is computed over.

    Was a bare ``since`` with an open upper end, which is right for "the last
    30 days" and cannot express "that Tuesday" or "1–15 September". A pair
    covers both, and `covers` keeps the two-sided form out of seven call
    sites — an upper bound silently dropped from one of them is how a funnel
    stops agreeing with the summary above it.
    """

    since: datetime
    #: Exclusive. ``None`` means "up to now", which is what a preset range is.
    until: datetime | None = None
    #: Retail, B2B, or both. `Order.merchant_id` is the whole distinction.
    channel: AnalyticsChannel = AnalyticsChannel.ALL

    @property
    def channel_filter(self) -> tuple[ColumnElement[bool], ...]:
        """The predicate scoping a query to one half of the business."""
        if self.channel is AnalyticsChannel.RETAIL:
            return (Order.merchant_id.is_(None),)
        if self.channel is AnalyticsChannel.B2B:
            return (Order.merchant_id.isnot(None),)
        return ()

    def covers(
        self, column: InstrumentedAttribute[datetime | None]
    ) -> tuple[ColumnElement[bool], ...]:
        """Predicates pinning ``column`` inside the window."""
        if self.until is None:
            return (column >= self.since,)
        return (column >= self.since, column < self.until)


async def build_business_analytics(
    db: AsyncSession,
    *,
    r: AnalyticsRange | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    channel: AnalyticsChannel = AnalyticsChannel.ALL,
) -> BusinessAnalyticsOut:
    """Business tab: revenue, margin (approx), funnel, product mix, customers.

    Either a preset range or an explicit ``since``/``until``. The explicit form
    is what the calendar asks for — one day when a cell is clicked, one month
    to paint the grid, an arbitrary span when somebody picks two dates — and it
    is the same computation, not a second one.

    ``channel`` narrows every figure to retail or to B2B. The two halves of the
    business have different margins and different failure modes, and a blended
    number hides both; the comparison block is the deliberate exception and
    stays whole whatever is asked for.
    """
    moment = now()
    if since is None:
        r = r or AnalyticsRange.D30
        since = moment - timedelta(days=range_to_days(r))
    window = Scope(since=since, until=until, channel=channel)

    # The KPI card ("Заказов" / "оплачено N") and the funnel below it must never
    # disagree, so both are built from the *same* created_at-windowed status
    # counts — one query, two consumers. See ``_funnel`` and ``_business_summary``.
    status_counts = await _status_counts_since(db, window)
    funnel = _funnel(status_counts)
    summary = await _business_summary(db, window, status_counts)
    revenue_series = await _revenue_series(db, window)
    top_brands = await _top_brands(db, window)
    top_skus = await _top_skus(db, window)
    customers = await _customers(db, window)
    channels = await _channels(db, window)
    hourly = await _hourly(db, window)
    previous = await _previous_summary(db, window, moment)

    return BusinessAnalyticsOut(
        generated_at=moment,
        range=r,
        channel=channel,
        since=window.since,
        until=window.until,
        summary=summary,
        revenue_series=revenue_series,
        funnel=funnel,
        top_brands=top_brands,
        top_skus=top_skus,
        customers=customers,
        channels=channels,
        hourly=hourly,
        previous=previous,
    )


def _margin_parts() -> tuple[Any, Any, Any]:
    """Known revenue, known cost, and units whose cost we do not know.

    Extracted so the headline margin and the per-day series are the same
    arithmetic rather than two copies of it — a calendar whose days do not add
    up to the number above them is worse than no calendar.

    Fixed SKUs with a known cost contribute price and cost; variable-amount
    (Steam) ones are priced off a multiplier, so the markup is the margin;
    fixed ones with no known cost contribute only to the unknown-unit count,
    because an unknown cost must never read as a 100% margin.
    """
    return (
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
            func.sum(OrderItem.qty).filter(Sku.variable_amount.is_(False), Sku.cost_usdt.is_(None)),
            0,
        ),
    )


async def _previous_summary(
    db: AsyncSession, window: Scope, moment: datetime
) -> BusinessSummaryOut | None:
    """The same summary over the window of equal length immediately before.

    Every headline on this tab was an absolute: "1486 orders" is neither good
    nor bad without the number it replaced. The comparison window is derived
    from this one rather than configured, so it is always like-for-like — a
    30-day figure is never compared against a week.

    `None` when nothing was sold before the window, which is the honest answer
    for a shop's first month rather than a misleading "+100%".
    """
    length = (window.until or moment) - window.since
    earlier = Scope(since=window.since - length, until=window.since, channel=window.channel)
    counts = await _status_counts_since(db, earlier)
    summary = await _business_summary(db, earlier, counts)
    return None if summary.orders == 0 and summary.gmv_usd == 0 else summary


async def _business_summary(
    db: AsyncSession, window: Scope, status_counts: dict[str, int]
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
            .where(
                IS_SALE,
                *window.covers(Order.paid_at),
                *window.channel_filter,
                Order.status.in_(_PAID_LIKE),
            )
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
    # See ``orders.revenue.margin_usd_expr`` and the design doc referenced there.
    m = (
        select(*_margin_parts())
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Sku, Sku.id == OrderItem.sku_id)
        .where(*window.covers(Order.paid_at), *window.channel_filter, Order.status.in_(_PAID_LIKE))
    )
    known_rev_raw, known_cost_raw, unknown_units = (await db.execute(m)).one()
    known_rev = Decimal(str(known_rev_raw or 0))
    known_cost = Decimal(str(known_cost_raw or 0))
    margin = known_rev - known_cost
    margin_pct = float(margin / known_rev * 100) if known_rev > 0 else 0.0
    # Refunds, in money. The funnel counts them in orders, which says nothing
    # about what they cost: one refunded Steam top-up and one refunded voucher
    # are one number each and two very different holes.
    refunded_raw = (
        await db.execute(
            select(func.coalesce(func.sum(gross.c.charged_usd), 0))
            .select_from(Order)
            .join(gross, gross.c.order_id == Order.id, isouter=True)
            .where(
                IS_SALE,
                *window.covers(Order.paid_at),
                *window.channel_filter,
                Order.status == "refunded",
            )
        )
    ).scalar_one()

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
        refunded_usd=Decimal(str(refunded_raw or 0)),
    )


async def _revenue_series(db: AsyncSession, window: Scope) -> list[RevenuePoint]:
    """Revenue, order count and approximate margin, one row per day.

    Two queries rather than one: revenue is per *order* and margin is per
    *order item*, so a single grouped statement would multiply the revenue by
    the number of lines on each order. They are joined by date in Python,
    where that cannot happen.
    """
    day = _local_day(Order.paid_at)
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
        .where(
            IS_SALE,
            *window.covers(Order.paid_at),
            *window.channel_filter,
            Order.status.in_(_PAID_LIKE),
        )
        .group_by(day)
        .order_by(day)
    )
    rows = (await db.execute(stmt)).all()

    item_day = _local_day(Order.paid_at)
    margins = (
        select(item_day.label("d"), *_margin_parts())
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Sku, Sku.id == OrderItem.sku_id)
        .where(
            IS_SALE,
            *window.covers(Order.paid_at),
            *window.channel_filter,
            Order.status.in_(_PAID_LIKE),
        )
        .group_by(item_day)
    )
    by_day: dict[date_cls, tuple[Decimal, int]] = {}
    for d, known_rev, known_cost, unknown in (await db.execute(margins)).all():
        if d is None:
            continue
        key = d.date() if hasattr(d, "date") else d
        by_day[key] = (
            Decimal(str(known_rev or 0)) - Decimal(str(known_cost or 0)),
            int(unknown or 0),
        )

    out: list[RevenuePoint] = []
    for d, rev, c in rows:
        if d is None:
            continue
        key = d.date() if hasattr(d, "date") else d
        margin, unknown_units = by_day.get(key, (None, 0))
        out.append(
            RevenuePoint(
                date=key,
                revenue_usd=Decimal(str(rev or 0)),
                orders=int(c or 0),
                margin_usd=margin,
                margin_unknown_units=unknown_units,
            )
        )
    return out


async def _channels(db: AsyncSession, window: Scope) -> list[ChannelStatOut]:
    """Retail against B2B.

    `IS_SALE` is `purpose == "catalog"`, which is both of them, so every
    headline on this tab has been one blended figure — and the two have
    genuinely different economics: a reseller buys at a wholesale price with a
    thinner markup, so a good B2B month reads as a margin collapse when it is
    averaged into retail. `merchant_id` is the whole distinction and was used
    nowhere in analytics.

    Deliberately **not** scoped by ``window.channel``: this block is the
    comparison, and filtering it to one side would collapse it to a single
    bar. It stays the full picture even while the rest of the tab is drilled
    into one half.
    """
    gross = order_charged_usd_subq()
    is_b2b = Order.merchant_id.isnot(None)
    stmt = (
        select(
            is_b2b.label("b2b"),
            func.coalesce(func.sum(gross.c.charged_usd), 0),
            func.count(Order.id),
        )
        .select_from(Order)
        .join(gross, gross.c.order_id == Order.id, isouter=True)
        .where(IS_SALE, *window.covers(Order.paid_at), Order.status.in_(_PAID_LIKE))
        .group_by(is_b2b)
    )
    revenue = {
        bool(b2b): (Decimal(str(g or 0)), int(c or 0))
        for b2b, g, c in (await db.execute(stmt)).all()
    }

    margins = (
        select(is_b2b.label("b2b"), *_margin_parts())
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Sku, Sku.id == OrderItem.sku_id)
        .where(IS_SALE, *window.covers(Order.paid_at), Order.status.in_(_PAID_LIKE))
        .group_by(is_b2b)
    )
    margin_by: dict[bool, Decimal] = {}
    for b2b, known_rev, known_cost, _unknown in (await db.execute(margins)).all():
        margin_by[bool(b2b)] = Decimal(str(known_rev or 0)) - Decimal(str(known_cost or 0))

    out: list[ChannelStatOut] = []
    for b2b, name in ((False, "retail"), (True, "b2b")):
        gmv, orders = revenue.get(b2b, (Decimal("0"), 0))
        out.append(
            ChannelStatOut(
                channel=name,
                gmv_usd=gmv,
                orders=orders,
                margin_usd=margin_by.get(b2b),
            )
        )
    return out


async def _hourly(db: AsyncSession, window: Scope) -> list[HourPoint]:
    """Orders by hour of the **local** day.

    `paid_at` is stored UTC, and Uzbekistan is +5 — read raw, the evening peak
    lands at lunchtime and every conclusion drawn from it is wrong by five
    hours. Postgres converts, so the hour is the one an operator recognises.
    """
    gross = order_charged_usd_subq()
    hour = func.extract("hour", func.timezone(_LOCAL_TZ, Order.paid_at))
    stmt = (
        select(
            hour.label("h"),
            func.count(Order.id),
            func.coalesce(func.sum(gross.c.charged_usd), 0),
        )
        .select_from(Order)
        .join(gross, gross.c.order_id == Order.id, isouter=True)
        .where(
            IS_SALE,
            *window.covers(Order.paid_at),
            *window.channel_filter,
            Order.status.in_(_PAID_LIKE),
        )
        .group_by(hour)
    )
    found = {
        int(h): (int(c or 0), Decimal(str(rev or 0)))
        for h, c, rev in (await db.execute(stmt)).all()
        if h is not None
    }
    # Every hour, including the empty ones: a chart with gaps in it reads as
    # missing data rather than as a quiet night.
    return [
        HourPoint(
            hour=h,
            orders=found.get(h, (0, Decimal("0")))[0],
            revenue_usd=found.get(h, (0, Decimal("0")))[1],
        )
        for h in range(24)
    ]


async def _status_counts_since(db: AsyncSession, window: Scope) -> dict[str, int]:
    """Order counts by current status, for orders *created* inside the window.

    Single source of truth for both the funnel and the "orders" / "paid
    orders" / "delivered orders" KPI headlines — see ``build_business_analytics``.
    """
    stmt = (
        select(Order.status, func.count())
        .where(IS_SALE, *window.covers(Order.created_at), *window.channel_filter)
        .group_by(Order.status)
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


async def _top_brands(db: AsyncSession, window: Scope) -> list[BrandRevenueOut]:
    stmt = (
        select(
            Brand.slug,
            func.coalesce(func.sum(OrderItem.qty * OrderItem.unit_price_usd), 0),
            func.coalesce(func.sum(OrderItem.qty), 0),
            # Margin (fixed known-cost + variable/Steam) — NULL when the group
            # has no costable rows. See ``orders.revenue.margin_usd_expr``.
            func.sum(margin_usd_expr()),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Sku, Sku.id == OrderItem.sku_id)
        .join(Product, Product.id == Sku.product_id)
        .join(Brand, Brand.id == Product.brand_id)
        .where(*window.covers(Order.paid_at), *window.channel_filter, Order.status.in_(_PAID_LIKE))
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


async def _top_skus(db: AsyncSession, window: Scope) -> list[SkuRevenueOut]:
    stmt = (
        select(
            Sku.sku_code,
            func.coalesce(func.sum(OrderItem.qty * OrderItem.unit_price_usd), 0),
            func.coalesce(func.sum(OrderItem.qty), 0),
            # Margin (fixed known-cost + variable/Steam) — NULL when the group
            # has no costable rows. See ``orders.revenue.margin_usd_expr``.
            func.sum(margin_usd_expr()),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Sku, Sku.id == OrderItem.sku_id)
        .where(*window.covers(Order.paid_at), *window.channel_filter, Order.status.in_(_PAID_LIKE))
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


async def _customers(db: AsyncSession, window: Scope) -> CustomersOut:
    day = _local_day(User.created_at)
    new_rows = (
        await db.execute(
            select(day.label("d"), func.count())
            # Not channel-filtered: a registration is not an order, and a
            # reseller signs up through the cabinet, not through this series.
            .where(*window.covers(User.created_at))
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
                    IS_SALE,
                    *window.covers(Order.created_at),
                    *window.channel_filter,
                    Order.user_id.is_(None),
                )
            )
        ).scalar_one()
        or 0
    )
    registered = int(
        (
            await db.execute(
                select(func.count(Order.id)).where(
                    IS_SALE,
                    *window.covers(Order.created_at),
                    *window.channel_filter,
                    Order.user_id.isnot(None),
                )
            )
        ).scalar_one()
        or 0
    )

    # repeat rate: of distinct users with >=1 order in window, share with >=2.
    per_user = (
        await db.execute(
            select(Order.user_id, func.count(Order.id))
            .where(
                IS_SALE,
                *window.covers(Order.created_at),
                *window.channel_filter,
                Order.user_id.isnot(None),
            )
            .group_by(Order.user_id)
        )
    ).all()
    total_users = len(per_user)
    repeat = sum(1 for _u, c in per_user if int(c) >= 2)
    repeat_pct = round(repeat / total_users * 100, 2) if total_users else 0.0

    locale_rows = (
        await db.execute(
            select(User.locale, func.count())
            # Not channel-filtered: a registration is not an order, and a
            # reseller signs up through the cabinet, not through this series.
            .where(*window.covers(User.created_at))
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
