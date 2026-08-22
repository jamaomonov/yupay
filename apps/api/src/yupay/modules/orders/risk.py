"""Whether a paid order may be fulfilled automatically. See ADR-0047.

Kept apart from both ``payments`` and ``fulfillment``: the decision is neither
about taking money nor about delivering goods, and putting it in either would
mean the next rule (velocity, repeat cards, a small order followed hours later
by a large one) lands wherever it was convenient rather than where it belongs.

Nothing here blocks a sale. Payment already happened; the only question is
whether a human looks before the goods leave, and holding is reversible in one
click while an issued game code is not.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from yupay.core.config import Settings, get_settings
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.orders.models import OrderEvent

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.orders.models import Order

log = get_logger("yupay.orders.risk")

#: Written to ``order_events`` and shown in the alert.
REASON_LARGE_AMOUNT = "amount_at_or_above_threshold"

#: The acquirer debited the customer after we had already written the order
#: off as expired. The sale is real, but it was priced and stocked ten minutes
#: ago and nobody expected it any more, so a human decides whether to deliver
#: or refund.
REASON_PAID_AFTER_EXPIRY = "paid_after_order_expired"


#: reason -> (alert title, what the operator should do). Kept beside the
#: reasons rather than inside ``hold_for_review`` so adding a rule without
#: wording it is a visible omission: the old text said "крупный заказ"
#: whatever the reason was, and the second rule made it a lie.
HOLD_ALERT_TEXT: dict[str, tuple[str, str]] = {
    REASON_LARGE_AMOUNT: (
        "🔍 Крупный заказ — на проверке",
        "Оплачен, выдача НЕ запущена. Проверь плательщика, затем выдай или верни деньги.",
    ),
    REASON_PAID_AFTER_EXPIRY: (
        "🔍 Оплата пришла на истёкший заказ",
        "Заказ уже был закрыт, когда пришли деньги. Выдача НЕ запущена — "
        "реши, выдавать или вернуть. Для пополнения кошелька: зачислить вручную "
        "или вернуть, см. runbook paid-after-expiry.",
    ),
}


def review_reason(order: Order, *, settings: Settings | None = None) -> str | None:
    """Why this order must not be fulfilled automatically, or ``None``.

    Returns a reason string rather than a bool so the event log and the alert
    can say which rule fired — with one rule that is pedantic, with three it is
    the difference between a useful log line and a shrug.
    """
    cfg = settings or get_settings()
    threshold = cfg.manual_review_threshold_usd
    if threshold > 0 and order.total_usd >= threshold:
        return REASON_LARGE_AMOUNT
    return None


async def hold_for_review(db: AsyncSession, *, order: Order, reason: str) -> None:
    """Record the hold and tell an operator. Never raises.

    The order keeps status ``paid``: the customer's view stays "processing",
    which is what it honestly is, and no new state has to be taught to the
    storefront, the mini app and the FSM. Fulfilment simply never starts, and
    ``fulfillment.start_for_order`` accepts a ``paid`` order, so releasing the
    hold later is the same call that would have run now.
    """
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind="order.held_for_review",
            payload={"reason": reason, "total_usd": str(order.total_usd)},
            actor="risk",
        )
    )
    log.warning("orders.held_for_review", order_id=order.id, reason=reason)

    # Pre-arm the stuck-order watchdog's per-order key so its first reminder
    # lands one repeat window from now instead of 15 minutes from now. Without
    # this a held order produces two alerts in quarter of an hour, and an alert
    # channel that repeats itself is one that stops being read.
    with contextlib.suppress(Exception):
        cfg = get_settings()
        await get_redis().set(
            f"alert:stuck_order:{order.id}",
            "1",
            ex=cfg.stuck_order_alert_repeat_hours * 3600,
            nx=True,
        )

    from yupay.modules.notifications.alerts import send_admin_alert

    charged = f"{order.total_charged:,.0f}".replace(",", " ")
    title, what_to_do = HOLD_ALERT_TEXT.get(reason, HOLD_ALERT_TEXT[REASON_LARGE_AMOUNT])
    with contextlib.suppress(Exception):
        await send_admin_alert(
            f"<b>{title}</b>\n"
            f"Заказ: <code>{order.id[:8]}…</code>\n"
            f"Сумма: <b>{charged} {order.currency}</b> (${order.total_usd})\n"
            f"<i>{what_to_do}</i>",
            kind="order_held_for_review",
        )


__all__ = [
    "HOLD_ALERT_TEXT",
    "REASON_LARGE_AMOUNT",
    "REASON_PAID_AFTER_EXPIRY",
    "hold_for_review",
    "review_reason",
]
