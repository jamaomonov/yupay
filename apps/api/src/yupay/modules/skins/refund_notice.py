"""Telling a buyer their skin purchase fell through and the money is on the balance.

Two channels, both after commit so a refund that rolls back tells nobody: ``order.refunded``
over the order socket (a nudge — the page re-reads the order and the balance), and the bot. Used by
the automatic refund in fulfilment and by an admin's refund from the trades screen.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.logging import get_logger
from yupay.modules.orders.models import Order

log = get_logger("yupay.skins.refund_notice")


async def tell_buyer_refunded(db: AsyncSession, *, order_id: str, try_later: bool) -> None:
    """After commit: push ``order.refunded`` and message the bot.

    Both wait for the commit — a page told before it would re-read an unchanged order,
    and a rolled-back refund must tell nobody. A lost push is logged, never raised.

    Args:
        db: The session the refund was written in.
        order_id: The refunded order.
        try_later: Waxpeer was short of our balance — the bot suggests a retry soon.
    """
    from yupay.modules.notifications import api as notifications

    user_id = (
        await db.execute(select(Order.user_id).where(Order.id == order_id))
    ).scalar_one_or_none()

    async def _tell() -> bool:
        await _push(user_id, order_id)
        return await notifications.notify_skin_refunded(order_id, try_later=try_later)

    notifications.schedule_after_commit(db, _tell)


async def _push(user_id: str | None, order_id: str) -> None:
    from yupay.modules.realtime import api as realtime

    try:
        await realtime.publish_order_event(
            user_id, {"type": "order.refunded", "orderId": order_id, "to": "wallet"}
        )
    except Exception as exc:  # noqa: BLE001 -- a lost nudge must not read as a failed refund
        log.warning("skins.refund_push_failed", order_id=order_id, error=str(exc)[:200])


__all__ = ["tell_buyer_refunded"]
