"""Whether an order has a CS2 skin still on its way to the buyer.

Waxpeer cannot recall an offer we paid for. While a skin line is being bought or its
offer sits in Steam, refunding the order — an acquirer's cancel or an admin's refund —
would hand the buyer the skin *and* the money. The line is on its way until it is
``delivered`` (the delivered-goods guards take over) or ``failed`` with the money accounted
for (see :func:`_settled`).

A line counts as a skin by its SKU, so a line the worker has not claimed yet is caught
too, or by its trade row.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from sqlalchemy import and_, exists, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from yupay.modules.catalog.models import Sku
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.skins.checkout import CS2_SKIN_SKU_CODE
from yupay.modules.skins.models import SkinTrade
from yupay.modules.skins.trade_view import SkinRefundedTo

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from yupay.modules.payments.models import Payment

#: What a failed line's task recorded when we know where the money is: Waxpeer gave it
#: back, or it was spent on a skin that was rolled back.
_ACCOUNTED = ("returned", "spent")


def _settled() -> ColumnElement[bool]:
    """Received, or failed with the money accounted for — or settled by an operator.

    A failure with ``unknown`` money (``ambiguous_trade``, ``buy_unconfirmed``) is not
    settled: a skin may have been bought and its offer may still be open in Steam. It stays
    blocked until an operator checks Waxpeer and marks the trade «Разобрано».
    """
    accounted = exists().where(
        FulfillmentTask.order_item_id == OrderItem.id,
        FulfillmentTask.extra_metadata["money_outcome"].astext.in_(_ACCOUNTED),
    )
    resolved = exists().where(
        SkinTrade.order_item_id == OrderItem.id, SkinTrade.resolved_at.is_not(None)
    )
    return or_(
        OrderItem.fulfillment_state == "delivered",
        and_(OrderItem.fulfillment_state == "failed", or_(accounted, resolved)),
    )


async def skin_trade_in_flight(db: AsyncSession, order_id: str) -> bool:
    """``True`` if a skin line of the order is still being bought or sent, or failed in a
    way that may have left an offer open.

    Locks the order row first: a refund and a fulfilment retry both lock it before they
    check, so one of them always sees what the other did (the retry side is
    ``fulfillment.service._refuse_a_refunded_retail_order``).

    Args:
        db: Session; the lock is held until the caller's transaction ends.
        order_id: The order about to be refunded.
    """
    await db.execute(select(Order.id).where(Order.id == order_id).with_for_update())
    is_skin = or_(
        exists().where(SkinTrade.order_item_id == OrderItem.id),
        exists().where(Sku.id == OrderItem.sku_id, Sku.sku_code == CS2_SKIN_SKU_CODE),
    )
    row = (
        await db.execute(
            select(OrderItem.id)
            .where(OrderItem.order_id == order_id, not_(_settled()), is_skin)
            .limit(1)
        )
    ).first()
    return row is not None


def refund_destination(payments: Iterable[Payment]) -> SkinRefundedTo | None:
    """Where an order's money went back, if it did: the balance or the card.

    Args:
        payments: The order's payments.
    """
    from yupay.modules.payments.service import refunded_to_wallet

    refunded = [p for p in payments if p.status == "refunded"]
    if not refunded:
        return None
    return "wallet" if any(refunded_to_wallet(p) for p in refunded) else "card"


__all__ = ["refund_destination", "skin_trade_in_flight"]
