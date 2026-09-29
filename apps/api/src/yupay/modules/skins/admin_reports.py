"""Skins for the admin: sales and margin over a period, and one customer's Steam side.

Sales are counted by trade creation date (Tashkent days). A line is *sold* once received
(``delivered``), *failed* once Waxpeer gave the money back, *in flight* otherwise. Revenue is
what the customer was charged for the line in USD; cost is what Waxpeer charged us
(``bought_units``, else the listing's ``paid_units``), in thousandths of a dollar.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from yupay.core.clock import now
from yupay.core.errors import ValidationError
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.skins.admin_trades import AdminSkinTradeOut, payments_by_order, trade_out
from yupay.modules.skins.models import SkinTrade, SkinTradeLink
from yupay.modules.skins.order_display import skin_images
from yupay.modules.skins.tradelink import STEAM64_BASE, parse_tradelink

_UNITS_PER_USD = Decimal(1000)
_TZ = "Asia/Tashkent"


class SalesTotals(BaseModel):
    """A group of trades: how many, and their money."""

    count: int
    revenue_usd: Decimal
    cost_usd: Decimal
    margin_usd: Decimal


class SalesDay(BaseModel):
    """One Tashkent day of received skins."""

    day: date
    count: int
    revenue_usd: Decimal
    margin_usd: Decimal


class SkinsSummaryOut(BaseModel):
    """Sales and margin over the last ``days`` days."""

    days: int
    sold: SalesTotals
    failed: SalesTotals
    in_flight: SalesTotals
    by_day: list[SalesDay]


def _cost() -> ColumnElement[float | Decimal]:
    return func.coalesce(SkinTrade.bought_units, SkinTrade.paid_units) / _UNITS_PER_USD


async def sales_summary(db: AsyncSession, *, days: int) -> SkinsSummaryOut:
    """Received, failed and in-flight skins since ``days`` days ago, and received per day.

    Args:
        db: Session.
        days: The window, counted back from now.
    """
    since = now() - timedelta(days=days)
    group = case(
        (OrderItem.fulfillment_state == "delivered", "sold"),
        (OrderItem.fulfillment_state == "failed", "failed"),
        else_="in_flight",
    ).label("grp")
    revenue = OrderItem.unit_price_usd * OrderItem.qty - func.coalesce(OrderItem.discount_usd, 0)
    cost = _cost()
    base = (
        select(SkinTrade)
        .join(OrderItem, OrderItem.id == SkinTrade.order_item_id)
        .where(SkinTrade.created_at >= since)
    )
    rows = (
        await db.execute(
            base.with_only_columns(
                group,
                func.count(),
                func.coalesce(func.sum(revenue), 0),
                func.coalesce(func.sum(cost), 0),
            ).group_by(group)
        )
    ).all()
    totals = {
        grp: SalesTotals(
            count=int(n),
            revenue_usd=Decimal(rev),
            cost_usd=Decimal(c),
            margin_usd=Decimal(rev) - Decimal(c),
        )
        for grp, n, rev, c in rows
    }
    zero = SalesTotals(count=0, revenue_usd=Decimal(0), cost_usd=Decimal(0), margin_usd=Decimal(0))
    day = cast(func.timezone(_TZ, SkinTrade.created_at), Date).label("day")
    per_day = (
        await db.execute(
            base.where(OrderItem.fulfillment_state == "delivered")
            .with_only_columns(
                day,
                func.count(),
                func.coalesce(func.sum(revenue), 0),
                func.coalesce(func.sum(revenue - cost), 0),
            )
            .group_by(day)
            .order_by(day.desc())
        )
    ).all()
    return SkinsSummaryOut(
        days=days,
        sold=totals.get("sold", zero),
        failed=totals.get("failed", zero),
        in_flight=totals.get("in_flight", zero),
        by_day=[
            SalesDay(day=d, count=int(n), revenue_usd=Decimal(r), margin_usd=Decimal(m))
            for d, n, r, m in per_day
        ],
    )


class SteamAccountOut(BaseModel):
    """A Steam account — never the trade link: its token is a credential."""

    steam_id: str
    profile_url: str


class SavedLinkOut(SteamAccountOut):
    """The customer's saved trade link, as its account."""

    updated_at: datetime


class OrderedAccountOut(SteamAccountOut):
    """An account the customer's skin orders went to."""

    orders: int


class CustomerSkinsOut(BaseModel):
    """One customer's Steam side: the saved link, the accounts ordered to, the last trades."""

    saved: SavedLinkOut | None
    accounts: list[OrderedAccountOut]
    trades: list[AdminSkinTradeOut]


def _steam_id(raw: str) -> int | None:
    """The account behind a trade link; ``None`` for one we cannot read (not counted)."""
    try:
        return parse_tradelink(raw).partner + STEAM64_BASE
    except ValidationError:
        return None


def _profile(steam_id: int) -> str:
    return f"https://steamcommunity.com/profiles/{steam_id}"


async def customer_skins(db: AsyncSession, *, user_id: str, limit: int = 20) -> CustomerSkinsOut:
    """What the customer card shows about CS2 skins.

    Args:
        db: Session.
        user_id: The customer.
        limit: How many recent trades.
    """
    link = await db.get(SkinTradeLink, user_id)
    rows = (
        await db.execute(
            select(SkinTrade, OrderItem, FulfillmentTask)
            .join(OrderItem, OrderItem.id == SkinTrade.order_item_id)
            .join(Order, Order.id == OrderItem.order_id)
            .outerjoin(FulfillmentTask, FulfillmentTask.id == SkinTrade.task_id)
            .where(Order.user_id == user_id)
            .order_by(SkinTrade.created_at.desc(), SkinTrade.id.desc())
        )
    ).all()
    counts: dict[int, int] = {}
    for _, item, _ in rows:
        steam_id = _steam_id(str((item.fulfillment_data or {}).get("tradelink") or ""))
        if steam_id is not None:
            counts[steam_id] = counts.get(steam_id, 0) + 1
    page = rows[:limit]
    images = await skin_images(
        db, (str((item.fulfillment_data or {}).get("slug") or "") for _, item, _ in page)
    )
    payments = await payments_by_order(db, {item.order_id for _, item, _ in page})
    return CustomerSkinsOut(
        saved=(
            SavedLinkOut(
                steam_id=str(link.steam_id),
                profile_url=_profile(link.steam_id),
                updated_at=link.updated_at,
            )
            if link is not None
            else None
        ),
        accounts=[
            OrderedAccountOut(steam_id=str(sid), profile_url=_profile(sid), orders=n)
            for sid, n in sorted(counts.items(), key=lambda kv: -kv[1])
        ],
        trades=[
            trade_out(row, item, task, images, payments.get(item.order_id))
            for row, item, task in page
        ],
    )


__all__ = ["CustomerSkinsOut", "SkinsSummaryOut", "customer_skins", "sales_summary"]
