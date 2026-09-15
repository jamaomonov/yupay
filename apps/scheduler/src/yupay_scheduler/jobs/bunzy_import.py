"""Pull the day's Bunzy article in as a blog draft.

Never publishes and never overwrites an editor's work — :mod:`yupay.modules
.blog.bunzy_import` holds both rules and the reasons for them. This file is
only the schedule and the failure isolation: one session per article, so a
malformed feed entry cannot roll back the one before it, and a Bunzy outage
costs a log line rather than a scheduler restart.

Disabled unless ``BUNZY_API_KEY`` is set, which is the dev and CI default.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.blog.bunzy_client import BunzyClient, BunzyUnavailableError, is_configured
from yupay.modules.blog.bunzy_import import stale_slugs, sync_post

from yupay_scheduler.startup import first_run_after

log = get_logger("yupay.scheduler.bunzy_import")

_JOB_ID = "blog.bunzy_import"


async def run_bunzy_import() -> None:
    """Fetch the feed, then import each article that changed since last pass."""
    if not is_configured():
        return
    settings = get_settings()
    factory = get_session_factory()
    async with BunzyClient() as client:
        try:
            summaries = await client.list_posts(limit=settings.bunzy_import_page_size)
        except (BunzyUnavailableError, OSError) as exc:
            log.warning("bunzy.feed_unavailable", error=str(exc))
            return
        async with factory() as session, session.begin():
            slugs = await stale_slugs(session, summaries)
        if not slugs:
            log.info("bunzy.up_to_date", seen=len(summaries))
            return
        tally: dict[str, int] = {}
        for slug in slugs:
            outcome = await _one(client, factory, slug)
            tally[outcome] = tally.get(outcome, 0) + 1
    log.info("bunzy.pass_done", seen=len(summaries), fetched=len(slugs), **tally)


async def _one(
    client: BunzyClient,
    factory: async_sessionmaker[AsyncSession],
    slug: str,
) -> str:
    """Import one article. Returns the outcome name, or ``failed``."""
    try:
        post = await client.get_post(slug)
    except (BunzyUnavailableError, OSError, ValueError) as exc:
        log.warning("bunzy.fetch_failed", slug=slug, error=str(exc))
        return "failed"
    try:
        async with factory() as session, session.begin():
            result = await sync_post(session, post)
    except Exception:
        log.exception("bunzy.import_failed", slug=slug)
        return "failed"
    return result.outcome


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job. Safe to call once at startup; a no-op without a key."""
    if not is_configured():
        log.info("bunzy.disabled")
        return
    minutes = get_settings().bunzy_import_interval_minutes
    scheduler.add_job(
        run_bunzy_import,
        trigger="interval",
        minutes=minutes,
        id=_JOB_ID,
        # Without this the first run is a whole interval after boot, so a
        # container restarting more often than that never imports anything.
        next_run_time=first_run_after(120),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("bunzy.registered", interval_minutes=minutes)


__all__ = ["register", "run_bunzy_import"]
