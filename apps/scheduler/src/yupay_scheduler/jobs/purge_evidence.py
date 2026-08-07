"""Delete chargeback captures past their retention date.

Runs daily. The retention promise made in the privacy notice is only real if
something enforces it, and this job is that something — without it the table
becomes an ever-growing store of unhashed IPs, which is exactly what ADR-0044
argues against.

Deliberately not hourly: nothing depends on same-day deletion, and a daily
sweep keeps the write amplification off the busy path.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger

# Reach into ``service`` rather than ``evidence.api``: the latter imports the
# admin router, which drags the whole route stack into the scheduler process.
# Same reasoning as ``expire_orders``.
from yupay.modules.evidence.service import purge_expired

log = get_logger("yupay.scheduler.purge_evidence")

_JOB_ID = "evidence.purge_expired"
_INTERVAL_HOURS = 24


async def run_purge_expired_evidence() -> None:
    """One scheduler tick, in its own session/transaction."""
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            count = await purge_expired(session)
        if count:
            log.info("evidence.purge_expired.deleted", count=count)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to ``scheduler``."""
    scheduler.add_job(
        run_purge_expired_evidence,
        trigger="interval",
        hours=_INTERVAL_HOURS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("evidence.purge_expired.registered", interval_hours=_INTERVAL_HOURS)


__all__ = ["register", "run_purge_expired_evidence"]
