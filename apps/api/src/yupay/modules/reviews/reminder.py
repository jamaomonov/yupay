"""A second ask, in Telegram, for a delivered order nobody rated.

The delivery message carries an «Оценить заказ» button, but it arrives with
the codes — at the moment the buyer is leaving for the game. Nothing followed
it. The in-app catch-up is the only other prompt and it requires opening the
Mini App again and landing on home or history, so a buyer who got their code
and went back to playing was never asked again.

Measured on production 2026-09-14: 45 reviews against 714 delivered retail
orders in 60 days.

**Ships off** (``review_reminder_after_hours`` defaults to 0), like
``risk_device_identity`` and ``risk_hold_auto_refund_hours`` before it. This
one messages real customers, so switching it on is a decision somebody makes
on purpose rather than a side effect of a deploy.

Two caps keep it from becoming spam, and they are the reason this is a query
rather than a loop over orders:

* one order per user per run (``DISTINCT ON (user_id)``, newest first);
* nothing at all to a user reminded within :data:`REMINDER_USER_COOLDOWN`.

Together they mean somebody with nine unreviewed orders hears from us once a
week about the newest one, not nine times in an hour.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.notifications.api import notify_review_reminder
from yupay.modules.orders.models import Order, OrderEvent
from yupay.modules.reviews.models import Review
from yupay.modules.reviews.pending import PENDING_ASK_MAX_AGE

log = get_logger("yupay.reviews.reminder")

#: Written to ``order_events`` so an order is never reminded twice, and so the
#: per-user cooldown has something to read. An event rather than a column: the
#: fact is "we sent this on that date", which is what this table is for, and it
#: needs no migration to start recording.
REMINDER_EVENT = "review.reminder_sent"

#: No second message to the same person inside this window, whatever else of
#: theirs is unreviewed.
REMINDER_USER_COOLDOWN = timedelta(days=7)

#: Per tick. Small on purpose — this sends Telegram messages one at a time.
BATCH_LIMIT = 50


async def send_review_reminders(
    db: AsyncSession, *, settings: Settings | None = None, limit: int = BATCH_LIMIT
) -> int:
    """Remind up to ``limit`` buyers about one unreviewed order each.

    Returns the number of messages actually sent. Each send commits on its own
    so a failure halfway through neither loses the reminders already recorded
    nor re-sends them on the next tick.

    Args:
        db: Session.
        settings: Override for tests.
        limit: Ceiling on messages this call may send.

    Returns:
        How many reminders went out.
    """
    cfg = settings or get_settings()
    if cfg.review_reminder_after_hours <= 0:
        return 0

    moment = now()
    ripe = moment - timedelta(hours=cfg.review_reminder_after_hours)
    stale = moment - PENDING_ASK_MAX_AGE

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

    rows = (
        await db.execute(
            select(Order.id, Order.user_id)
            .distinct(Order.user_id)
            .where(
                Order.status == "delivered",
                Order.purpose == "catalog",
                Order.merchant_id.is_(None),
                Order.user_id.is_not(None),
                Order.delivered_at.is_not(None),
                Order.delivered_at <= ripe,
                Order.delivered_at >= stale,
                ~select(Review.id).where(Review.order_id == Order.id).exists(),
                ~reminded_order,
                ~reminded_user,
            )
            .order_by(Order.user_id, Order.delivered_at.desc())
            .limit(limit)
        )
    ).all()

    sent = 0
    for order_id, user_id in rows:
        if user_id is None:  # pragma: no cover -- excluded by the query above
            continue
        try:
            delivered = await notify_review_reminder(db, order_id=order_id, user_id=user_id)
            if not delivered:
                # No linked Telegram, or the surface is unconfigured. Record it
                # anyway: without the event this order is re-selected every
                # tick forever, and re-asking a channel that does not exist is
                # not a thing worth retrying.
                _record(db, order_id, delivered=False)
                await db.commit()
                continue
            _record(db, order_id, delivered=True)
            await db.commit()
            sent += 1
        except Exception:
            # One unreachable chat must not stop the batch. Roll back to a
            # clean session so the next order's write is not poisoned.
            await db.rollback()
            log.exception("reviews.reminder_failed", order_id=order_id)

    if sent:
        log.info("reviews.reminders_sent", count=sent)
    return sent


def _record(db: AsyncSession, order_id: str, *, delivered: bool) -> None:
    """Mark this order as asked about, whether or not a message left."""
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
    "REMINDER_EVENT",
    "REMINDER_USER_COOLDOWN",
    "send_review_reminders",
]
