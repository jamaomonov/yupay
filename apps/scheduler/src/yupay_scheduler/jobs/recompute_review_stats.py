"""Nightly reconcile of denormalized brand rating stats (drift safety net).

``brand_rating_stats`` is bumped transactionally on every review status change,
so it should always match the truth. This periodic sweep rebuilds every brand's
row from its ``published`` reviews anyway — cheap insurance against any drift a
crash mid-transaction or a future code path might introduce. Runs once a day.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.reviews.service import recompute_all_stats

log = get_logger("yupay.scheduler.recompute_review_stats")

_JOB_ID = "reviews.recompute_stats"


async def run_recompute_review_stats() -> None:
    """One tick: rebuild every brand's rating stats from published reviews."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        touched = await recompute_all_stats(session)
    log.info("recompute_review_stats.tick", brands=touched)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the nightly job to a running scheduler. Safe to call once at startup."""
    scheduler.add_job(
        run_recompute_review_stats,
        trigger="cron",
        hour=3,
        minute=15,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("recompute_review_stats.registered")


__all__ = ["register", "run_recompute_review_stats"]
