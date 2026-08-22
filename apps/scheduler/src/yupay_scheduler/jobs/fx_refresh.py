"""Refresh FX history and trip payments if a watched quote dumped.

Runs every ``FX_REFRESH_INTERVAL_MINUTES`` minutes (default 5). The
comparison and the kill-switch live in ``fx.refresh_and_trip`` so an
admin force-refresh takes the same path.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.fx.tripwire import refresh_and_trip

log = get_logger("yupay.scheduler.fx_refresh")

_JOB_ID = "fx.refresh"


async def run_fx_refresh() -> None:
    """One scheduler tick: write ``fx_rates``, maybe trip providers."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        drops, tripped = await refresh_and_trip(session)
    log.info(
        "fx.refresh.tick",
        drops=[d.quote for d in drops],
        tripped=tripped,
    )


def register(scheduler: AsyncIOScheduler) -> None:
    minutes = max(1, int(get_settings().fx_refresh_interval_minutes))
    scheduler.add_job(
        run_fx_refresh,
        trigger="interval",
        minutes=minutes,
        id=_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=_JOB_ID, interval_minutes=minutes)
