"""One Telegram nudge for an order that expired before it was paid.

Thin wrapper: the selection query and its caps live in
``orders.unpaid_reminder.send_unpaid_reminders``, where the api test suite
can drive them directly.

Every five minutes: orders expire at ten, the service waits
``unpaid_reminder_after_minutes`` from creation, and a nudge an hour late
misses the moment. Off when the setting is 0 — the job still ticks, the
service returns immediately.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.orders.unpaid_reminder import send_unpaid_reminders

log = get_logger("yupay.scheduler.unpaid_reminder")

_JOB_ID = "orders.remind_unpaid"
_INTERVAL_MINUTES = 5


async def run_unpaid_reminder() -> None:
    """One tick: up to ``BATCH_LIMIT`` buyers, one order each."""
    factory = get_session_factory()
    async with factory() as session:
        sent = await send_unpaid_reminders(session)
    if sent:
        log.info("unpaid_reminder.tick", sent=sent)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    scheduler.add_job(
        run_unpaid_reminder,
        trigger="interval",
        minutes=_INTERVAL_MINUTES,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,  # one tick at a time; the batch is not re-entrant.
        coalesce=True,
    )


__all__ = ["register", "run_unpaid_reminder"]
