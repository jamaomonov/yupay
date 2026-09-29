"""Every skin trade for the admin screen, and which of them a human must settle.

Rows come from ``skin_trades`` (written before the first Waxpeer call, so even a purchase
Waxpeer never confirmed has one), joined to the order line for its order and fulfilment
state and to the task for whether the buy is still unconfirmed. Three views:

* ``all`` — every trade, newest first;
* ``active`` — not settled yet: buying, offer out, or accepted and under Steam protection;
* ``attention`` — a rollback after delivery (status 6 with penalties), a purchase we could
  not confirm (``buy_unconfirmed`` / ``ambiguous_trade``), or a buy still unconfirmed on an
  in-flight task with no Waxpeer status yet — until an operator marks it resolved
  (:func:`resolve_trade`), which is what keeps the view a to-do list and not a history.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import String, and_, cast, false, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from yupay.core.clock import now
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import OrderItem
from yupay.modules.payments.models import Payment
from yupay.modules.skins.models import SkinTrade
from yupay.modules.skins.order_display import skin_images
from yupay.modules.skins.refund_guard import refund_destination
from yupay.modules.skins.trade_view import (
    SkinRefundedTo,
    SkinTradeReason,
    SkinTradeState,
    skin_trade_out,
)

TradesView = Literal["all", "active", "attention"]

_SUPPORT_REASONS = ("buy_unconfirmed", "ambiguous_trade")


class AdminSkinTradeOut(BaseModel):
    """One skin trade as an operator sees it."""

    id: str
    #: Our key on Waxpeer — what their dashboard is searched by.
    project_id: str
    waxpeer_id: int | None
    order_id: str
    order_item_id: str
    created_at: datetime
    market_hash_name: str
    phase: str
    image_url: str | None
    #: What the customer was charged for the line, in USD (the margin's other half).
    sold_usd: Decimal
    paid_units: int
    bought_units: int | None
    waxpeer_status: int | None
    state: SkinTradeState
    reason_code: SkinTradeReason | None
    reason: str | None
    penalties: Any
    seller_name: str | None
    trade_id: str | None
    offer_url: str | None
    send_until: datetime | None
    release_date: datetime | None
    accepted_at: datetime | None
    last_checked_at: datetime | None
    task_id: str | None
    task_status: str | None
    task_sub_state: Literal["buy_pending", "buy_unconfirmed"] | None
    #: Where the order's money went back, if it did.
    refunded_to: SkinRefundedTo | None
    #: The money is still ours and the line has settled (received or failed): «Вернуть деньги».
    can_refund: bool
    #: The task failed and nothing was refunded: «Повторить» (the fulfilment retry).
    can_retry: bool
    resolved_at: datetime | None
    resolved_note: str | None
    attention: bool


class TradeCounts(BaseModel):
    """How many trades are in flight and how many need a human — the tab badges."""

    active: int
    attention: int


class AdminSkinTradesOut(BaseModel):
    """A page of trades, how many match, and the tab counts (search ignored)."""

    items: list[AdminSkinTradeOut]
    total: int
    counts: TradeCounts


#: A buy whose lookup failed is retried every 5 s; only one still pending after this
#: long is stuck enough for a human.
PENDING_ATTENTION_AFTER = timedelta(minutes=5)

# The SQL filter and the per-row flag below say the same thing twice (one filters a page,
# the other labels a row); ``test_skins_admin_trades`` pins that they agree.


def _has_penalties() -> ColumnElement[bool]:
    """Penalties are an object or list with something in it — Waxpeer's shape."""
    text = cast(SkinTrade.penalties, String)
    return and_(
        func.jsonb_typeof(SkinTrade.penalties).in_(("object", "array")),
        text.not_in(("[]", "{}")),
    )


def _penalised(penalties: object) -> bool:
    return isinstance(penalties, dict | list) and len(penalties) > 0


def _unconfirmed_task() -> ColumnElement[bool]:
    meta = FulfillmentTask.extra_metadata
    return and_(
        FulfillmentTask.status == "in_progress",
        SkinTrade.status.is_(None),
        or_(
            func.coalesce(meta["buy_unconfirmed_at"].astext, "") != "",
            and_(
                meta["buy_pending"].astext == "true",
                FulfillmentTask.created_at < now() - PENDING_ATTENTION_AFTER,
            ),
        ),
    )


def _attention() -> ColumnElement[bool]:
    return and_(
        SkinTrade.resolved_at.is_(None),
        or_(
            and_(SkinTrade.status == 6, _has_penalties()),
            SkinTrade.reason.in_(_SUPPORT_REASONS),
            func.coalesce(_unconfirmed_task(), false()),
        ),
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


def _is_attention(row: SkinTrade, task: FulfillmentTask | None, sub_state: str | None) -> bool:
    if row.resolved_at is not None:
        return False
    rolled_back = row.status == 6 and _penalised(row.penalties)
    stuck = sub_state == "buy_unconfirmed" or (
        sub_state == "buy_pending"
        and task is not None
        and task.created_at < now() - PENDING_ATTENTION_AFTER
    )
    return rolled_back or row.reason in _SUPPORT_REASONS or stuck


def trade_out(
    row: SkinTrade,
    item: OrderItem,
    task: FulfillmentTask | None,
    images: dict[str, str | None] | None = None,
    payments: list[Payment] | None = None,
) -> AdminSkinTradeOut:
    """One trade as the screen shows it; ``payments`` are its order's, for the refund."""
    view = skin_trade_out(row, fulfillment_state=item.fulfillment_state)
    sub_state = _sub_state(task, row)
    refunded_to = refund_destination(payments or [])
    ours = refunded_to is None and any(p.status == "succeeded" for p in payments or [])
    return AdminSkinTradeOut(
        id=row.id,
        project_id=row.project_id,
        waxpeer_id=row.waxpeer_id,
        order_id=item.order_id,
        order_item_id=item.id,
        created_at=row.created_at,
        market_hash_name=row.market_hash_name,
        phase=row.phase or "",
        image_url=(images or {}).get(str((item.fulfillment_data or {}).get("slug") or "")),
        sold_usd=item.unit_price_usd,
        paid_units=row.paid_units,
        bought_units=row.bought_units,
        waxpeer_status=row.status,
        state=view.state,
        reason_code=view.reason_code,
        reason=row.reason,
        penalties=row.penalties,
        seller_name=(row.seller or {}).get("name"),
        trade_id=row.trade_id,
        offer_url=view.offer_url,
        send_until=row.send_until,
        release_date=row.release_date,
        accepted_at=row.accepted_at,
        last_checked_at=row.last_checked_at,
        task_id=task.id if task is not None else None,
        task_status=task.status if task is not None else None,
        task_sub_state=sub_state,
        refunded_to=refunded_to,
        can_refund=ours and item.fulfillment_state in ("delivered", "failed"),
        can_retry=ours and task is not None and task.status == "failed",
        resolved_at=row.resolved_at,
        resolved_note=row.resolved_note,
        attention=_is_attention(row, task, sub_state),
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
                # autoescape: an admin's "_" or "%" is a character, not a wildcard.
                cast(OrderItem.order_id, String).startswith(needle.lower(), autoescape=True),
                SkinTrade.market_hash_name.icontains(needle, autoescape=True),
            )
        )
    base = (
        select(SkinTrade, OrderItem, FulfillmentTask)
        .join(OrderItem, OrderItem.id == SkinTrade.order_item_id)
        .outerjoin(FulfillmentTask, FulfillmentTask.id == SkinTrade.task_id)
        .where(*where)
    )
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    page = (
        await db.execute(
            base.order_by(SkinTrade.created_at.desc(), SkinTrade.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    images = await skin_images(
        db, (str((item.fulfillment_data or {}).get("slug") or "") for _, item, _ in page)
    )
    payments = await payments_by_order(db, {item.order_id for _, item, _ in page})
    return AdminSkinTradesOut(
        items=[
            trade_out(row, item, task, images, payments.get(item.order_id))
            for row, item, task in page
        ],
        total=int(total),
        counts=await _counts(db),
    )


async def payments_by_order(db: AsyncSession, order_ids: set[str]) -> dict[str, list[Payment]]:
    """Every payment of these orders, one query — for where each refund went."""
    if not order_ids:
        return {}
    rows = (await db.execute(select(Payment).where(Payment.order_id.in_(order_ids)))).scalars()
    out: dict[str, list[Payment]] = {}
    for p in rows:
        out.setdefault(p.order_id, []).append(p)
    return out


async def load_trade(db: AsyncSession, trade_id: str) -> AdminSkinTradeOut | None:
    """One trade as the screen shows it, or ``None``."""
    found = (
        await db.execute(
            select(SkinTrade, OrderItem, FulfillmentTask)
            .join(OrderItem, OrderItem.id == SkinTrade.order_item_id)
            .outerjoin(FulfillmentTask, FulfillmentTask.id == SkinTrade.task_id)
            .where(SkinTrade.id == trade_id)
        )
    ).first()
    if found is None:
        return None
    row, item, task = found
    images = await skin_images(db, [str((item.fulfillment_data or {}).get("slug") or "")])
    payments = await payments_by_order(db, {item.order_id})
    return trade_out(row, item, task, images, payments.get(item.order_id))


async def _counts(db: AsyncSession) -> TradeCounts:
    joined = (
        select(func.count())
        .select_from(SkinTrade)
        .join(OrderItem, OrderItem.id == SkinTrade.order_item_id)
        .outerjoin(FulfillmentTask, FulfillmentTask.id == SkinTrade.task_id)
    )
    active = (await db.execute(joined.where(_active()))).scalar_one()
    attention = (await db.execute(joined.where(_attention()))).scalar_one()
    return TradeCounts(active=int(active), attention=int(attention))


async def resolve_trade(
    db: AsyncSession, *, trade_id: str, by: str, note: str | None = None
) -> AdminSkinTradeOut | None:
    """Mark a trade settled by a human; it leaves the ``attention`` view. Idempotent.

    Args:
        db: Active session; committed here.
        trade_id: ``skin_trades.id``.
        by: The operator's user id.
        note: What was done (a refund, a support answer, a Waxpeer ticket).

    Returns:
        The trade as the screen shows it, or ``None`` when there is no such trade.
    """
    found = (
        await db.execute(
            select(SkinTrade, OrderItem, FulfillmentTask)
            .join(OrderItem, OrderItem.id == SkinTrade.order_item_id)
            .outerjoin(FulfillmentTask, FulfillmentTask.id == SkinTrade.task_id)
            .where(SkinTrade.id == trade_id)
            .with_for_update(of=SkinTrade)
        )
    ).first()
    if found is None:
        return None
    row = found[0]
    if row.resolved_at is None:
        row.resolved_at = now()
        row.resolved_by = by
        row.resolved_note = (note or "").strip() or None
        await db.commit()
    return await load_trade(db, trade_id)


__all__ = [
    "AdminSkinTradeOut",
    "AdminSkinTradesOut",
    "TradeCounts",
    "TradesView",
    "list_trades",
    "load_trade",
    "payments_by_order",
    "resolve_trade",
    "trade_out",
]
