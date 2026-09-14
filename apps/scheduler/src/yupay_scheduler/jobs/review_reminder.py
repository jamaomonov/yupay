"""One Telegram reminder for a delivered order the buyer never rated.

Thin wrapper, the pattern every job in this directory uses: the selection
query, the per-user caps, and the per-order failure isolation all live in
``reviews.reminder.send_review_reminders``, where the api test suite can drive
them directly.

Hourly rather than every few minutes. The thing being waited for is a person
deciding to write something, which does not move on a 15-minute clock, and the
service already refuses to send anything until an order is
``review_reminder_after_hours`` old.

Off until ``REVIEW_REMINDER_AFTER_HOURS`` is set — the job still ticks, the
service returns 0 immediately. Registering it unconditionally keeps the
"is it on" answer in exactly one place (the setting) instead of two.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.reviews.reminder import send_review_reminders

log = get_logger("yupay.scheduler.review_reminder")

_JOB_ID = "reviews.remind_unrated"
_INTERVAL_MINUTES = 60


async def run_review_reminder() -> None:
    """One tick: up to ``BATCH_LIMIT`` buyers, one order each."""
    factory = get_session_factory()
    async with factory() as session:
        sent = await send_review_reminders(session)
    if sent:
        log.info("review_reminder.tick", sent=sent)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    scheduler.add_job(
        run_review_reminder,
        trigger="interval",
        minutes=_INTERVAL_MINUTES,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,  # one tick at a time; the batch is not re-entrant.
    )


__all__ = ["register", "run_review_reminder"]
