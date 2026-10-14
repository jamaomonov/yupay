"""One Telegram nudge for an order that expired before it was paid.

An order lives ten minutes (``ORDER_EXPIRY_SECONDS``). Measured on production
2026-10-14: 1225 of 4084 retail orders in 30 days expired unpaid ($8.9k), 1151
of them after the buyer had already opened a payment. 416 came back and paid
a new order within a day on their own; the rest did not, and nothing asked
them to.

The message sends the buyer to the brand's page in the Mini App, not to the
dead order — an expired order cannot be paid.

Who is asked, and the caps that keep it from becoming spam:

* signed-in buyers only (``user_id``) — a Telegram link is the channel; a guest
  has none, and an unrequested email about an abandoned cart is worse than
  silence;
* only after ``unpaid_reminder_after_minutes`` from creation, so the buyer
  has a few minutes to come back by themselves first, and never after
  :data:`MAX_AGE`, when the moment has passed;
* not when the same user already made a later order that was paid or is
  still awaiting payment — they came back without us;
* one order per user per run (``DISTINCT ON (user_id)``, newest first) and
  nothing to a user reminded within :data:`REMINDER_USER_COOLDOWN`.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.notifications.api import notify_unpaid_reminder
from yupay.modules.orders.models import Order, OrderEvent

log = get_logger("yupay.orders.unpaid_reminder")

#: Written to ``order_events`` so an order is never reminded twice, and so the
#: per-user cooldown has something to read.
REMINDER_EVENT = "order.unpaid_reminder_sent"

#: No second message to the same person inside this window.
REMINDER_USER_COOLDOWN = timedelta(hours=24)

#: Older than this, an unpaid order is not worth a message.
MAX_AGE = timedelta(hours=3)

#: Per tick. Telegram messages go out one at a time.
BATCH_LIMIT = 50


async def send_unpaid_reminders(
    db: AsyncSession, *, settings: Settings | None = None, limit: int = BATCH_LIMIT
) -> int:
    """Nudge up to ``limit`` buyers about one expired, unpaid order each.

    Each send commits on its own so a failure halfway through neither loses
    the reminders already recorded nor re-sends them on the next tick.

    Args:
        db: Session.
        settings: Override for tests.
        limit: Ceiling on messages this call may send.

    Returns:
        How many reminders went out.
    """
    cfg = settings or get_settings()
    if cfg.unpaid_reminder_after_minutes <= 0:
        return 0

    moment = now()
    ripe = moment - timedelta(minutes=cfg.unpaid_reminder_after_minutes)

    reminded_order = (
        select(OrderEvent.id)
        .where(OrderEvent.order_id == Order.id, OrderEvent.kind == REMINDER_EVENT)
        .exists()
    )
    other = aliased(Order)
    reminded_user = (
        select(OrderEvent.id)
        .join(other, other.id == OrderEvent.order_id)
        .where(
            other.user_id == Order.user_id,
            OrderEvent.kind == REMINDER_EVENT,
            OrderEvent.created_at >= moment - REMINDER_USER_COOLDOWN,
        )
        .exists()
    )
    later = aliased(Order)
    came_back = (
        select(later.id)
        .where(
            later.user_id == Order.user_id,
            later.created_at > Order.created_at,
            or_(later.paid_at.is_not(None), later.status == "pending_payment"),
        )
        .exists()
    )

    rows = (
        await db.execute(
            select(Order.id, Order.user_id)
            .distinct(Order.user_id)
            .where(
                Order.status == "expired",
                Order.purpose == "catalog",
                Order.merchant_id.is_(None),
                Order.user_id.is_not(None),
                Order.paid_at.is_(None),
                Order.created_at <= ripe,
                Order.created_at >= moment - MAX_AGE,
                ~came_back,
                ~reminded_order,
                ~reminded_user,
            )
            .order_by(Order.user_id, Order.created_at.desc())
            .limit(limit)
        )
    ).all()

    sent = 0
    for order_id, user_id in rows:
        if user_id is None:  # pragma: no cover -- excluded by the query above
            continue
        try:
            delivered = await notify_unpaid_reminder(db, order_id=order_id, user_id=user_id)
            # Recorded either way: without the event an order with no linked
            # Telegram is re-selected every tick until it ages out.
            _record(db, order_id, delivered=delivered)
            await db.commit()
            if delivered:
                sent += 1
        except Exception:
            # One unreachable chat must not stop the batch.
            await db.rollback()
            log.exception("orders.unpaid_reminder_failed", order_id=order_id)

    if sent:
        log.info("orders.unpaid_reminders_sent", count=sent)
    return sent


def _record(db: AsyncSession, order_id: str, *, delivered: bool) -> None:
    """Mark this order as nudged about, whether or not a message left."""
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order_id,
            kind=REMINDER_EVENT,
            payload={"delivered": delivered},
            actor="scheduler",
        )
    )


__all__ = [
    "BATCH_LIMIT",
    "MAX_AGE",
    "REMINDER_EVENT",
    "REMINDER_USER_COOLDOWN",
    "send_unpaid_reminders",
]
