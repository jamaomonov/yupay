"""Alert on orders that were paid and never delivered.

Exists because of a real incident: on 2026-08-07 the largest order the platform
had ever taken failed two seconds after payment (the supplier balance was
exhausted), and sat undelivered for a day. The money was ours, the goods were
not the customer's, and nothing asked about it again.

Two design points follow directly from that incident.

**Keyed on the order, not on the failed task.** A failed fulfillment task is
only one way to end up here — an older production order had no task at all, so
a task-shaped query would have reported all clear while a paid customer waited.

**It repeats.** The low-balance alert that already existed fires once and
de-duplicates for 15 minutes; after that, silence, however long the order sits.
A watchdog that reminds once is a watchdog you can miss.
"""

from __future__ import annotations

import contextlib
import html

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis

# Reach into the services directly rather than through each module's ``api``:
# those import route modules, which drag the whole FastAPI router stack into the
# scheduler process. Same reasoning as ``expire_orders``.
from yupay.modules.notifications.alerts import send_admin_alert
from yupay.modules.orders.service import list_stuck_paid_orders

log = get_logger("yupay.scheduler.stuck_orders")

_JOB_ID = "orders.alert_stuck"
_INTERVAL_MINUTES = 5


async def _should_alert(order_id: str, *, repeat_hours: int) -> bool:
    """Rate-limit per order, so one stuck order is one message per window.

    Fails OPEN — if Redis is unreachable we would rather send a duplicate alert
    than stay quiet about money we are holding.
    """
    redis = get_redis()
    key = f"alert:stuck_order:{order_id}"
    with contextlib.suppress(Exception):
        if not await redis.set(key, "1", ex=repeat_hours * 3600, nx=True):
            return False
    return True


def _format(order_id: str, amount: str, currency: str, minutes: int, status: str) -> str:
    hours = minutes // 60
    waited = f"{hours} ч {minutes % 60} мин" if hours else f"{minutes} мин"
    return (
        "<b>🚨 Оплачен, но не выдан</b>\n"
        f"Заказ: <code>{html.escape(order_id[:8])}…</code>\n"
        f"Сумма: <b>{html.escape(amount)} {html.escape(currency)}</b>\n"
        f"Статус: <code>{html.escape(status)}</code> · ждёт <b>{waited}</b>\n"
        "<i>Деньги у нас, товара у клиента нет. Проверь Fulfilment Inbox: "
        "пополнить баланс и повторить, выдать вручную или вернуть деньги.</i>"
    )


async def run_alert_stuck_orders() -> None:
    """One scheduler tick, in its own session/transaction."""
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        orders = await list_stuck_paid_orders(
            session, older_than_minutes=settings.stuck_order_alert_after_minutes
        )

    if not orders:
        return

    alerted = 0
    for order in orders:
        if not await _should_alert(order.id, repeat_hours=settings.stuck_order_alert_repeat_hours):
            continue
        waited_minutes = int((now() - order.paid_at).total_seconds() // 60) if order.paid_at else 0
        await send_admin_alert(
            _format(
                order.id,
                f"{order.total_charged:,.0f}".replace(",", " "),
                order.currency,
                waited_minutes,
                order.status,
            ),
            kind="order_stuck",
        )
        alerted += 1

    # Logged even when every order was inside its repeat window: "3 stuck, 0
    # alerted" is the line that explains a quiet Telegram during an incident.
    log.warning("orders.stuck.detected", stuck=len(orders), alerted=alerted)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to ``scheduler``."""
    scheduler.add_job(
        run_alert_stuck_orders,
        trigger="interval",
        minutes=_INTERVAL_MINUTES,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("orders.stuck.registered", interval_minutes=_INTERVAL_MINUTES)


__all__ = ["register", "run_alert_stuck_orders"]
