"""Hourly smart routing (ADR-0108): keep managed SKUs on the right supplier.

Same interval as the price refresh and offset after it — the job reads the
costs that refresh writes. ``sourcing_settings.smart_mode`` decides whether a
run does anything (``off``), only logs (``shadow``) or moves routes (``on``).
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.sourcing.smart_routing import run_smart_routing

from yupay_scheduler.startup import first_run_after

log = get_logger("yupay.scheduler.smart_routing")

_JOB_ID = "sourcing.smart_routing"


async def run_smart_routing_tick() -> None:
    """One tick; the summary goes to the log."""
    report = await run_smart_routing()
    log.info(
        "sourcing.smart_routing.tick",
        mode=report.mode,
        checked=report.checked,
        moved=report.moved,
        proposed=report.proposed,
        blocked=report.blocked,
        quarantined=report.quarantined,
        errors=report.errors,
        reasons=report.reasons,
    )


def register(scheduler: AsyncIOScheduler) -> None:
    minutes = max(1, int(get_settings().price_refresh_interval_minutes))
    scheduler.add_job(
        run_smart_routing_tick,
        trigger="interval",
        minutes=minutes,
        id=_JOB_ID,
        # After the price refresh's own first run, so the first pass reads fresh costs.
        next_run_time=first_run_after(600),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
