"""Admin routes that act on skins or report on them: refund a trade to the buyer's balance,
sales and margin over a period, and one customer's Steam side.

Retrying a trade is the fulfilment retry (``POST /admin/fulfillment/tasks/{id}/retry``); the
trade row says when it may be pressed (``can_retry``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from yupay.modules.admin.deps import require_admin
from yupay.modules.orders.models import OrderItem
from yupay.modules.skins.admin_reports import (
    CustomerSkinsOut,
    SkinsSummaryOut,
    customer_skins,
    sales_summary,
)
from yupay.modules.skins.admin_trades import AdminSkinTradeOut, load_trade
from yupay.modules.skins.models import SkinTrade
from yupay.modules.skins.refund_guard import skin_trade_in_flight
from yupay.modules.skins.refund_notice import tell_buyer_refunded
from yupay.modules.users.models import User

ops_router = APIRouter(
    prefix="/admin/skins", tags=["admin:skins"], dependencies=[Depends(require_admin)]
)


async def refund_trade(db: AsyncSession, *, trade_id: str, admin_id: str) -> AdminSkinTradeOut:
    """Refund a trade's order to the buyer's YuPay balance, tell them, mark the trade settled.

    Args:
        db: Session; committed here.
        trade_id: ``skin_trades.id``.
        admin_id: The operator.

    Raises:
        NotFoundError: No such trade.
        ConflictError: ``skin_trade_in_flight`` (Waxpeer cannot recall the offer) or
            ``already_refunded``.
    """
    from yupay.core.clock import now
    from yupay.modules.payments.service import refund_order_to_wallet

    found = (
        await db.execute(
            select(SkinTrade, OrderItem.order_id)
            .join(OrderItem, OrderItem.id == SkinTrade.order_item_id)
            .where(SkinTrade.id == trade_id)
            .with_for_update(of=SkinTrade)
        )
    ).first()
    if found is None:
        raise NotFoundError("skin trade not found")
    row, order_id = found
    if await skin_trade_in_flight(db, order_id):
        raise ConflictError(
            "the skin is still being bought or sent; wait until it is received or fails",
            reason="skin_trade_in_flight",
        )
    refunded = await refund_order_to_wallet(
        db, order_id=order_id, reason="admin", actor=f"admin:{admin_id}"
    )
    if not refunded:
        raise ConflictError("the order was already refunded", reason="already_refunded")
    if row.resolved_at is None:
        row.resolved_at = now()
        row.resolved_by = admin_id
        row.resolved_note = "refunded to balance"
    await tell_buyer_refunded(db, order_id=order_id, try_later=False)
    await db.commit()
    out = await load_trade(db, trade_id)
    assert out is not None  # locked and committed above
    return out


@ops_router.post(
    "/trades/{trade_id}/refund",
    response_model=AdminSkinTradeOut,
    summary="Refund a skin trade's order to the buyer's YuPay balance",
)
async def admin_refund_trade(
    trade_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> AdminSkinTradeOut:
    """Refund to the balance (owner's rule for skins); refused while the skin is on its way."""
    key = normalize_idempotency_key(idempotency_key)
    if key is None:
        raise ValidationError("Idempotency-Key header is required", header=IDEMPOTENCY_HEADER)
    scope = f"skins.refund_trade:{trade_id}"
    cached = await load_replay(db, scope=scope, idempotency_key=key)
    if cached is not None and cached.body is not None:
        return AdminSkinTradeOut.model_validate(cached.body)
    out = await refund_trade(db, trade_id=trade_id, admin_id=str(admin.id))
    await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@ops_router.get(
    "/summary", response_model=SkinsSummaryOut, summary="Skin sales and margin over a period"
)
async def admin_skins_summary(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> SkinsSummaryOut:
    """Received, failed and in-flight skins, their revenue, cost and margin, and per day."""
    return await sales_summary(db, days=days)


@ops_router.get(
    "/customers/{user_id}",
    response_model=CustomerSkinsOut,
    summary="A customer's Steam accounts and skin trades",
)
async def admin_customer_skins(
    user_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> CustomerSkinsOut:
    """The saved trade link's account, the accounts ordered to, the last 20 trades."""
    return await customer_skins(db, user_id=user_id)


__all__ = ["ops_router", "refund_trade"]
