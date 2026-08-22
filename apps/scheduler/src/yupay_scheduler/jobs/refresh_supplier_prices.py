"""Periodically re-price every active supplier mapping.

Runs every ``PRICE_REFRESH_INTERVAL_MIN`` minutes (default 60). Each
mapping is processed in its own transaction inside
``integrations.price_refresh.refresh_all_mappings`` — a single supplier
hiccup never blocks the rest of the queue.

Telegram alerts on cost moves bigger than
``PRICE_ALERT_THRESHOLD_PCT`` go out through the dedicated admin bot
(``notifications.send_admin_alert``). The scheduler doesn't have to
care which bot — that's hidden behind ``notifications.api``.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.integrations.price_refresh import refresh_all_mappings

from yupay_scheduler.startup import first_run_after

log = get_logger("yupay.scheduler.refresh_supplier_prices")

_JOB_ID = "integrations.refresh_supplier_prices"


async def run_refresh_supplier_prices() -> None:
    """One scheduler tick. Logs the summary so ops can grep the run
    history without touching the DB."""
    report = await refresh_all_mappings()
    log.info(
        "integrations.refresh_supplier_prices.tick",
        checked=report.checked,
        moved=report.moved,
        alerts_sent=report.alerts_sent,
        errors=report.errors,
    )


def register(scheduler: AsyncIOScheduler) -> None:
    minutes = max(1, int(get_settings().price_refresh_interval_minutes))
    scheduler.add_job(
        run_refresh_supplier_prices,
        trigger="interval",
        minutes=minutes,
        id=_JOB_ID,
        # Without this the first run is a whole interval after boot, so a
        # restart more often than that means the job never runs at all.
        next_run_time=first_run_after(90),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=_JOB_ID, interval_minutes=minutes)
