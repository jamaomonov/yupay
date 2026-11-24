"""A refused one-time pack refunds itself to the buyer's balance (ADR-0108).

Free Fire's Level Up Packages are sold once per game account and only below
their level; a supplier refuses a player who already has one, and on prod that
was 42 % of «Level Up Package 6» orders. Every one of those refusals used to
wait for an operator to refund by hand. ``Sku.one_time_pack`` marks such a SKU,
and when its task fails with the money back (``MoneyOutcome.RETURNED``) on a
signed-in retail order, the money goes to the YuPay balance at once:

- an order of one line is refunded whole (``refund_order_to_wallet``);
- in a pack cart, only this line (``refund_line_to_wallet``), and only once
  another line has been delivered — otherwise the order stays with an operator,
  exactly as before.

Self-gated and replay-safe: both refunds are idempotent, and anything else —
another SKU, a merchant or guest order, money not confirmed back — returns
without touching anything.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.errors import ConflictError
from yupay.core.logging import get_logger
from yupay.modules.catalog.models import Sku
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers import MoneyOutcome
from yupay.modules.orders.models import Order, OrderItem

log = get_logger("yupay.fulfillment.one_time_pack")

#: The ``reason`` a whole-order refund records, and the actor of a line refund.
REFUND_REASON = "one_time_pack_refused"
_SYSTEM_ADMIN = "system:one_time_pack"


async def refund_refused_pack(db: AsyncSession, *, task_id: str, money_outcome_key: str) -> bool:
    """Refund a refused one-time pack to the balance; ``True`` when money moved now.

    Args:
        db: Session; the caller commits.
        task_id: The task that just failed.
        money_outcome_key: Where the task's metadata keeps its money outcome.
    """
    task = await db.get(FulfillmentTask, task_id)
    if task is None or task.status != "failed":
        return False
    if (task.extra_metadata or {}).get(money_outcome_key) != MoneyOutcome.RETURNED.value:
        return False
    item = await db.get(OrderItem, task.order_item_id)
    sku = await db.get(Sku, item.sku_id) if item is not None else None
    if item is None or sku is None or not sku.one_time_pack:
        return False
    order = await db.get(Order, task.order_id)
    if order is None or order.user_id is None or order.merchant_id is not None:
        return False
    lines = (
        await db.execute(select(func.count()).where(OrderItem.order_id == order.id))
    ).scalar_one()

    from yupay.modules.payments.line_refund import refund_line_to_wallet
    from yupay.modules.payments.service import refund_order_to_wallet

    amount: str | None = None
    try:
        async with db.begin_nested():
            if lines == 1:
                refunded = await refund_order_to_wallet(
                    db, order_id=order.id, reason=REFUND_REASON, actor=_SYSTEM_ADMIN
                )
            else:
                payment = await refund_line_to_wallet(
                    db,
                    order_item_id=item.id,
                    admin_id=_SYSTEM_ADMIN,
                    idempotency_key=f"one-time-pack:{item.id}",
                )
                entry = ((payment.extra_metadata or {}).get("line_refunds") or {}).get(item.id)
                amount = entry["amount"] if entry else None
                refunded = True
    except ConflictError as exc:
        # A cart whose other lines are still running, or a payment refunded some
        # other way: nothing moved, an operator settles it as before.
        log.info(
            "fulfillment.one_time_pack.left_to_operator",
            order_id=order.id,
            reason=str(exc)[:120],
        )
        return False
    if refunded:
        log.info("fulfillment.one_time_pack.refunded", order_id=order.id, lines=lines)
        _tell_buyer(db, order_id=order.id, user_id=order.user_id, sku_id=sku.id, amount=amount)
    return refunded


def _tell_buyer(
    db: AsyncSession, *, order_id: str, user_id: str, sku_id: str, amount: str | None
) -> None:
    """After commit: nudge the order page and message the bot."""
    from yupay.modules.notifications import api as notifications
    from yupay.modules.realtime import api as realtime

    async def _tell() -> bool:
        try:
            await realtime.publish_order_event(
                user_id, {"type": "order.refunded", "orderId": order_id, "to": "wallet"}
            )
        except Exception as exc:  # noqa: BLE001 -- a lost nudge must not read as a failed refund
            log.warning("fulfillment.one_time_pack.push_failed", error=str(exc)[:200])
        return await notifications.notify_pack_refunded(order_id, sku_id=sku_id, amount=amount)

    notifications.schedule_after_commit(db, _tell)


__all__ = ["REFUND_REASON", "refund_refused_pack"]
