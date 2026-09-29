"""Whether an order has a CS2 skin still on its way to the buyer.

Waxpeer cannot recall an offer we paid for. While a skin line is being bought or its
offer sits in Steam, refunding the order — an acquirer's cancel or an admin's refund —
would hand the buyer the skin *and* the money. The line is on its way until it is
``delivered`` (the delivered-goods guards take over) or ``failed`` (Waxpeer gave the
money back and it went to the buyer's balance).

A line counts as a skin by its SKU, so a line the worker has not claimed yet is caught
too, or by its trade row.
"""

from __future__ import annotations

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.catalog.models import Sku
from yupay.modules.orders.models import OrderItem
from yupay.modules.skins.checkout import CS2_SKIN_SKU_CODE
from yupay.modules.skins.models import SkinTrade

#: A skin line in one of these has finished travelling, one way or the other.
_SETTLED_STATES = ("delivered", "failed")


async def skin_trade_in_flight(db: AsyncSession, order_id: str) -> bool:
    """``True`` if a skin line of the order is still being bought or sent.

    Args:
        db: Session.
        order_id: The order about to be refunded.
    """
    is_skin = or_(
        exists().where(SkinTrade.order_item_id == OrderItem.id),
        exists().where(Sku.id == OrderItem.sku_id, Sku.sku_code == CS2_SKIN_SKU_CODE),
    )
    row = (
        await db.execute(
            select(OrderItem.id)
            .where(
                OrderItem.order_id == order_id,
                OrderItem.fulfillment_state.not_in(_SETTLED_STATES),
                is_skin,
            )
            .limit(1)
        )
    ).first()
    return row is not None


__all__ = ["skin_trade_in_flight"]
