"""Delete expired and revoked auth sessions.

On production this table was 86% garbage — 3551 of 4122 rows already expired or
revoked, with nothing ever removing any of them. It is the fastest-growing
table in the twelve-month projection at roughly seven rows per order, which at
the target volume is about 13 million rows and 5GB, almost all of it dead.

Nightly rather than hourly: nothing depends on same-day deletion, and a daily
sweep keeps the write amplification off the busy path. The first run after this
ships meets whatever has accumulated, so the sweep is batched and expected to
take several nights to catch up rather than doing it in one transaction.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger

# Reach into ``service`` rather than ``auth.api``: the facade imports the auth
# router, which drags the whole route stack into the scheduler process. Same
# reasoning as ``purge_evidence``.
from yupay.modules.auth.service import purge_stale_sessions

from yupay_scheduler.startup import first_run_after

log = get_logger("yupay.scheduler.purge_sessions")

_JOB_ID = "auth.purge_stale_sessions"
_INTERVAL_HOURS = 24


async def run_purge_stale_sessions() -> None:
    """One scheduler tick, in its own session/transaction."""
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            count = await purge_stale_sessions(session)
        if count:
            log.info("auth.purge_stale_sessions.deleted", count=count)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to ``scheduler``."""
    scheduler.add_job(
        run_purge_stale_sessions,
        trigger="interval",
        hours=_INTERVAL_HOURS,
        id=_JOB_ID,
        # Without this the first run is a whole interval after boot, so a
        # restart more often than that means the job never runs at all.
        # Offset from purge_evidence so two DELETE sweeps do not land together.
        next_run_time=first_run_after(270),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("auth.purge_stale_sessions.registered", interval_hours=_INTERVAL_HOURS)


__all__ = ["register", "run_purge_stale_sessions"]
