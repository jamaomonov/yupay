"""Every skin trade for the admin screen, and which of them a human must settle.

Rows come from ``skin_trades`` (written before the first Waxpeer call, so even a purchase
Waxpeer never confirmed has one), joined to the order line for its order and fulfilment
state and to the task for whether the buy is still unconfirmed. Three views:

* ``all`` — every trade, newest first;
* ``active`` — not settled yet: buying, offer out, or accepted and under Steam protection;
* ``attention`` — a rollback after delivery (status 6 with penalties), a purchase we could
  not confirm (``buy_unconfirmed`` / ``ambiguous_trade``), or a buy still unconfirmed on an
  in-flight task with no Waxpeer status yet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import String, and_, cast, false, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import OrderItem
from yupay.modules.skins.models import SkinTrade
from yupay.modules.skins.trade_view import SkinTradeReason, SkinTradeState, skin_trade_out

TradesView = Literal["all", "active", "attention"]

_SUPPORT_REASONS = ("buy_unconfirmed", "ambiguous_trade")


class AdminSkinTradeOut(BaseModel):
    """One skin trade as an operator sees it."""

    id: str
    order_id: str
    order_item_id: str
    created_at: datetime
    market_hash_name: str
    phase: str
    paid_units: int
    bought_units: int | None
    waxpeer_status: int | None
    state: SkinTradeState
    reason_code: SkinTradeReason | None
    reason: str | None
    penalties: Any
    seller_name: str | None
    trade_id: str | None
    send_until: datetime | None
    release_date: datetime | None
    accepted_at: datetime | None
    last_checked_at: datetime | None
    task_status: str | None
    task_sub_state: Literal["buy_pending", "buy_unconfirmed"] | None
    attention: bool


class AdminSkinTradesOut(BaseModel):
    """A page of trades plus how many match."""

    items: list[AdminSkinTradeOut]
    total: int


def _has_penalties() -> ColumnElement[bool]:
    text = cast(SkinTrade.penalties, String)
    return and_(SkinTrade.penalties.is_not(None), text.not_in(("null", "[]", "{}")))


def _unconfirmed_task() -> ColumnElement[bool]:
    meta = FulfillmentTask.extra_metadata
    return and_(
        FulfillmentTask.status == "in_progress",
        SkinTrade.status.is_(None),
        or_(meta["buy_pending"].astext == "true", meta.has_key("buy_unconfirmed_at")),
    )


def _attention() -> ColumnElement[bool]:
    return or_(
        and_(SkinTrade.status == 6, _has_penalties()),
        SkinTrade.reason.in_(_SUPPORT_REASONS),
        func.coalesce(_unconfirmed_task(), false()),
    )


def _active() -> ColumnElement[bool]:
    return and_(
        func.coalesce(SkinTrade.status, 0).not_in((5, 6)),
        not_(SkinTrade.is_released),
        OrderItem.fulfillment_state != "failed",
    )


def _sub_state(task: FulfillmentTask | None, row: SkinTrade) -> Any:
    if task is None or task.status != "in_progress" or row.status is not None:
        return None
    meta = task.extra_metadata or {}
    if meta.get("buy_unconfirmed_at"):
        return "buy_unconfirmed"
    return "buy_pending" if meta.get("buy_pending") else None


def _is_attention(row: SkinTrade, sub_state: str | None) -> bool:
    rolled_back = row.status == 6 and bool(row.penalties)
    return rolled_back or row.reason in _SUPPORT_REASONS or sub_state is not None


def _out(row: SkinTrade, item: OrderItem, task: FulfillmentTask | None) -> AdminSkinTradeOut:
    view = skin_trade_out(row, fulfillment_state=item.fulfillment_state)
    sub_state = _sub_state(task, row)
    return AdminSkinTradeOut(
        id=row.id,
        order_id=item.order_id,
        order_item_id=item.id,
        created_at=row.created_at,
        market_hash_name=row.market_hash_name,
        phase=row.phase or "",
        paid_units=row.paid_units,
        bought_units=row.bought_units,
        waxpeer_status=row.status,
        state=view.state,
        reason_code=view.reason_code,
        reason=row.reason,
        penalties=row.penalties,
        seller_name=(row.seller or {}).get("name"),
        trade_id=row.trade_id,
        send_until=row.send_until,
        release_date=row.release_date,
        accepted_at=row.accepted_at,
        last_checked_at=row.last_checked_at,
        task_status=task.status if task is not None else None,
        task_sub_state=sub_state,
        attention=_is_attention(row, sub_state),
    )


async def list_trades(
    db: AsyncSession, *, view: TradesView, q: str | None, limit: int, offset: int
) -> AdminSkinTradesOut:
    """A page of trades for the admin screen, newest first.

    Args:
        db: Active session.
        view: ``all``, ``active`` or ``attention`` (see the module docstring).
        q: An order id prefix or part of the item name.
        limit: Page size (clamped by the route).
        offset: Rows to skip.

    Returns:
        The page and the total matching.
    """
    where: list[ColumnElement[bool]] = []
    if view == "active":
        where.append(_active())
    elif view == "attention":
        where.append(_attention())
    if q and q.strip():
        needle = q.strip()
        where.append(
            or_(
                cast(OrderItem.order_id, String).startswith(needle.lower()),
                SkinTrade.market_hash_name.ilike(f"%{needle}%"),
            )
        )
    base = (
        select(SkinTrade, OrderItem, FulfillmentTask)
        .join(OrderItem, OrderItem.id == SkinTrade.order_item_id)
        .outerjoin(FulfillmentTask, FulfillmentTask.id == SkinTrade.task_id)
        .where(*where)
    )
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = await db.execute(
        base.order_by(SkinTrade.created_at.desc(), SkinTrade.id.desc()).limit(limit).offset(offset)
    )
    return AdminSkinTradesOut(
        items=[_out(row, item, task) for row, item, task in rows.all()], total=int(total)
    )


__all__ = ["AdminSkinTradeOut", "AdminSkinTradesOut", "TradesView", "list_trades"]
