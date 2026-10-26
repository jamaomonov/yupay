"""The cabinet's Statistics screen: orders, money, top brands and packs over a window.

**Aggregated in SQL, not batched in Python.** The dashboard's
``cabinet_summary`` reads the ledger order by order under a 500-order cap,
which is right for a glance at today and wrong for «all time»: the window here
can hold a merchant's whole history. So the ledger is joined once — every
charge and refund posting on this merchant's deposit, grouped by order — and
the counts, the chart and the tops are all ``GROUP BY`` over that one
per-order row set. The money rule is the dashboard's own: what an order cost
is its charge minus every refund booked against it, whenever that was posted.

**The browser names the window and the zone.** As with the summary, the
browser knows when its own day started; ``tz`` is its IANA zone, and the chart
buckets are cut on that clock so a «day» bar matches the dates on the Orders
list.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import ColumnElement, String, and_, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Subquery

from yupay.core.errors import ValidationError
from yupay.modules.catalog.models import Brand, BrandTranslation, Product, Sku
from yupay.modules.merchants import deposit
from yupay.modules.merchants.cabinet_orders import DEFAULT_LOCALE
from yupay.modules.merchants.cabinet_stats_schemas import (
    CabinetStatsBrandOut,
    CabinetStatsOut,
    CabinetStatsPointOut,
    CabinetStatsSkuOut,
    CabinetStatsTotalsOut,
    Granularity,
)
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.wallet import service as wallet_service
from yupay.modules.wallet.models import WalletAccount, WalletPosting, WalletTransaction

_ZERO: Final = Decimal("0")

#: How many brands and packs the tops list. A screen, not a report — the
#: Orders list and its CSV are the full answer.
TOP: Final = 10

#: Up to two days the chart is hourly, up to ~three months daily, then monthly.
#: Each bound keeps a bar chart readable on a phone: 48 / 92 bars at most.
_HOURLY_UP_TO: Final = timedelta(hours=48)
_DAILY_UP_TO: Final = timedelta(days=92)

#: Statuses that are still moving; everything else is an outcome.
_IN_FLIGHT: Final = ("pending_payment", "paid", "fulfilling")
_CANCELLED: Final = ("cancelled", "refunded")


def zone(name: str) -> ZoneInfo:
    """The caller's IANA zone, or a 422 — never a silent fall back to UTC."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValidationError("unknown time zone", code="bad_timezone") from exc


def granularity_for(span: timedelta) -> Granularity:
    """The bar width for a window of ``span``."""
    if span <= _HOURLY_UP_TO:
        return "hour"
    if span <= _DAILY_UP_TO:
        return "day"
    return "month"


def bucket_starts(
    start: datetime, end: datetime, granularity: Granularity, tz: ZoneInfo
) -> list[datetime]:
    """Every bucket start from the one holding ``start`` up to ``end``, on ``tz``'s clock.

    Stepped in **local wall time** and only then attached to the zone, so a day
    is a calendar day across a DST change, and a month is a calendar month.
    """
    local = start.astimezone(tz)
    if granularity == "hour":
        cur = local.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    elif granularity == "day":
        cur = local.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    else:
        cur = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    stop = end.astimezone(tz).replace(tzinfo=None)
    out: list[datetime] = []
    while cur <= stop:
        out.append(cur.replace(tzinfo=tz))
        if granularity == "hour":
            cur += timedelta(hours=1)
        elif granularity == "day":
            cur += timedelta(days=1)
        else:
            cur = cur.replace(year=cur.year + cur.month // 12, month=cur.month % 12 + 1)
    return out


def _per_order(merchant_id: str, start: datetime | None, end: datetime) -> Subquery:
    """One row per order in the window: status, time, channel, sku and net cost.

    The two ledger sums mirror ``deposit.charged_for_orders`` (the charge, by
    its ledger key) and ``deposit.refunded_for_orders`` (money back, by the
    order reference) — grouped over this merchant's whole deposit rather than
    over a list of ids, so the window can be any length.
    """
    normal = wallet_service.NORMAL_SIDE["merchant_deposit"]
    on_deposit = (
        WalletAccount.owner_type == "merchant",
        WalletAccount.owner_id == merchant_id,
        WalletAccount.kind == "merchant_deposit",
        WalletAccount.currency == deposit.DEPOSIT_CURRENCY,
    )
    prefix = deposit.CHARGE_KEY_PREFIX
    charged = (
        select(
            func.substr(WalletTransaction.idempotency_key, len(prefix) + 1).label("order_id"),
            func.sum(WalletPosting.amount).label("amount"),
        )
        .join(WalletAccount, WalletAccount.id == WalletPosting.account_id)
        .join(WalletTransaction, WalletTransaction.id == WalletPosting.transaction_id)
        .where(
            *on_deposit,
            WalletPosting.direction != normal,
            WalletTransaction.idempotency_key.startswith(prefix, autoescape=True),
        )
        .group_by(WalletTransaction.idempotency_key)
        .subquery()
    )
    refunded = (
        select(
            WalletTransaction.reference_id.label("order_id"),
            func.sum(WalletPosting.amount).label("amount"),
        )
        .join(WalletAccount, WalletAccount.id == WalletPosting.account_id)
        .join(WalletTransaction, WalletTransaction.id == WalletPosting.transaction_id)
        .where(
            *on_deposit,
            WalletPosting.direction == normal,
            WalletTransaction.reference_type == deposit.ORDER_REFERENCE_TYPE,
        )
        .group_by(WalletTransaction.reference_id)
        .subquery()
    )
    order_key = cast(Order.id, String)
    window: list[ColumnElement[bool]] = [Order.merchant_id == merchant_id, Order.created_at < end]
    if start is not None:
        window.append(Order.created_at >= start)
    back = func.coalesce(refunded.c.amount, literal(_ZERO))
    return (
        select(
            Order.id.label("id"),
            Order.status.label("status"),
            Order.created_at.label("created_at"),
            func.coalesce(Order.idempotency_key, "").startswith("manual-").label("manual"),
            OrderItem.sku_id.label("sku_id"),
            (func.coalesce(charged.c.amount, literal(_ZERO)) - back).label("net"),
            back.label("back"),
        )
        # A merchant order has exactly one line (``merchants.orders``).
        .join(OrderItem, OrderItem.order_id == Order.id)
        .outerjoin(charged, charged.c.order_id == order_key)
        .outerjoin(refunded, refunded.c.order_id == order_key)
        .where(*window)
        .subquery()
    )


def _counts(rows: Subquery) -> tuple[ColumnElement[int], ...]:
    """``orders, delivered, failed`` as aggregate columns over ``rows``."""
    return (
        func.count(),
        func.count().filter(rows.c.status == "delivered"),
        func.count().filter(rows.c.status == "failed"),
    )


async def _totals(
    db: AsyncSession, merchant_id: str, start: datetime | None, end: datetime
) -> CabinetStatsTotalsOut:
    rows = _per_order(merchant_id, start, end)
    orders, delivered, failed, in_flight, cancelled, spend, back, paid, paid_count = (
        await db.execute(
            select(
                *_counts(rows),
                func.count().filter(rows.c.status.in_(_IN_FLIGHT)),
                func.count().filter(rows.c.status.in_(_CANCELLED)),
                func.coalesce(func.sum(rows.c.net), _ZERO),
                func.coalesce(func.sum(rows.c.back), _ZERO),
                func.coalesce(func.sum(rows.c.net).filter(rows.c.net > 0), _ZERO),
                func.count().filter(rows.c.net > 0),
            )
        )
    ).one()
    return CabinetStatsTotalsOut(
        orders=orders,
        delivered=delivered,
        failed=failed,
        in_flight=in_flight,
        cancelled=cancelled,
        spend_usd=Decimal(spend),
        refunded_usd=Decimal(back),
        avg_order_usd=Decimal(paid) / paid_count if paid_count else _ZERO,
    )


async def _series(
    db: AsyncSession,
    rows: Subquery,
    buckets: Sequence[datetime],
    granularity: Granularity,
    tz: ZoneInfo,
) -> list[CabinetStatsPointOut]:
    # Postgres 16's three-argument ``date_trunc`` cuts on the zone's clock and
    # answers an instant, which compares equal to the bucket we stepped to.
    at = func.date_trunc(granularity, rows.c.created_at, tz.key).label("at")
    found = {
        row.at: row
        for row in (
            await db.execute(
                select(at, *_counts(rows), func.coalesce(func.sum(rows.c.net), _ZERO)).group_by(at)
            )
        ).all()
    }
    out = []
    for start in buckets:
        hit = found.get(start)
        out.append(
            CabinetStatsPointOut(
                at=start,
                orders=hit[1] if hit else 0,
                delivered=hit[2] if hit else 0,
                failed=hit[3] if hit else 0,
                spend_usd=Decimal(hit[4]) if hit else _ZERO,
            )
        )
    return out


async def _tops(
    db: AsyncSession, rows: Subquery
) -> tuple[list[CabinetStatsBrandOut], list[CabinetStatsSkuOut]]:
    """Top brands and top packs by spend, then by count."""
    wanted = aliased(BrandTranslation)
    name = func.coalesce(wanted.name, Brand.slug)
    spend = func.coalesce(func.sum(rows.c.net), _ZERO)
    joined = (
        select()
        .select_from(rows)
        .join(Sku, Sku.id == rows.c.sku_id)
        .join(Product, Product.id == Sku.product_id)
        .join(Brand, Brand.id == Product.brand_id)
        .outerjoin(wanted, and_(wanted.brand_id == Brand.id, wanted.locale == DEFAULT_LOCALE))
    )
    brand_rows = (
        await db.execute(
            joined.add_columns(
                name,
                Brand.logo_url,
                func.count(),
                func.count().filter(rows.c.status == "delivered"),
                func.count().filter(rows.c.status == "failed"),
                spend,
            )
            .group_by(Brand.id, name, Brand.logo_url)
            .order_by(spend.desc(), func.count().desc())
            .limit(TOP)
        )
    ).all()
    sku_rows = (
        await db.execute(
            joined.add_columns(name, Brand.logo_url, Sku.denomination, Sku.sku_code, func.count())
            .add_columns(func.count().filter(rows.c.status == "failed"), spend)
            .group_by(Sku.id, name, Brand.logo_url)
            .order_by(spend.desc(), func.count().desc())
            .limit(TOP)
        )
    ).all()
    brands = [
        CabinetStatsBrandOut(
            brand_name=b,
            logo_url=logo,
            orders=n,
            delivered=ok,
            failed=bad,
            spend_usd=Decimal(money),
        )
        for b, logo, n, ok, bad, money in brand_rows
    ]
    skus = [
        CabinetStatsSkuOut(
            brand_name=b,
            logo_url=logo,
            sku_name=denom,
            sku_code=code,
            orders=n,
            failed=bad,
            spend_usd=Decimal(money),
        )
        for b, logo, denom, code, n, bad, money in sku_rows
    ]
    return brands, skus


async def build(
    db: AsyncSession,
    *,
    merchant_id: str,
    since: datetime | None,
    until: datetime | None,
    tz_name: str,
    now: datetime,
) -> CabinetStatsOut:
    """Statistics for one merchant's orders placed in ``[since, until)``.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: From the signed-in operator, never from a request field.
        since: Start of the window, inclusive; ``None`` for all time.
        until: End of the window, exclusive; ``None`` for now.
        tz_name: The browser's IANA zone, for the chart's buckets.
        now: Current time.

    Returns:
        Totals, the same-length window before (unless all time), a gap-free
        chart, the top brands and packs, and the API/cabinet split.

    Raises:
        ValidationError: ``bad_timezone``, or ``bad_window`` when the window is
            empty, inverted or starts in the future.
    """
    tz = zone(tz_name)
    end = min(until, now) if until is not None else now
    if since is not None and since >= end:
        raise ValidationError("the window is empty", code="bad_window")

    totals = await _totals(db, merchant_id, since, end)
    previous = (
        await _totals(db, merchant_id, since - (end - since), since) if since is not None else None
    )

    start = since
    if start is None:
        first = (
            await db.execute(
                select(func.min(Order.created_at)).where(Order.merchant_id == merchant_id)
            )
        ).scalar_one_or_none()
        start = first or end
    granularity = granularity_for(end - start)
    rows = _per_order(merchant_id, since, end)
    series = await _series(db, rows, bucket_starts(start, end, granularity, tz), granularity, tz)
    brands, skus = await _tops(db, rows)
    api_orders, cabinet_orders = (
        await db.execute(
            select(
                func.count().filter(~rows.c.manual),
                func.count().filter(rows.c.manual),
            )
        )
    ).one()

    return CabinetStatsOut(
        since=since,
        until=end,
        granularity=granularity,
        totals=totals,
        previous=previous,
        series=series,
        brands=brands,
        skus=skus,
        api_orders=api_orders,
        cabinet_orders=cabinet_orders,
    )


__all__ = ["TOP", "bucket_starts", "build", "granularity_for", "zone"]
