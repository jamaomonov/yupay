"""Daily import of the CS2 item catalogue from ByMykel/CSGO-API (ADR-0093).

Metadata only — prices are ``skins_price_sync``'s. Skipped entirely while
``cs2_skins_sync_enabled`` is off, so a deploy with the flag down costs
nothing. ``max_instances=1``: an import takes a minute or two and must not
overlap itself.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.skins.bymykel import import_catalog

from yupay_scheduler.startup import first_run_after

log = get_logger("yupay.scheduler.skins_catalog_import")

_JOB_ID = "skins.catalog_import"


async def run_skins_catalog_import() -> None:
    """One tick: fetch every file and upsert, or log that the flag is off."""
    settings = get_settings()
    if not settings.cs2_skins_sync_enabled:
        log.info("skins.import.skipped", reason="cs2_skins_sync_enabled=false")
        return
    summary = await import_catalog(get_session_factory(), base_url=settings.bymykel_base_url)
    log.info("skins.import.done", files=summary.files, rows=summary.rows, changed=summary.changed)


def register(scheduler: AsyncIOScheduler) -> None:
    hours = max(1, int(get_settings().skins_import_interval_hours))
    scheduler.add_job(
        run_skins_catalog_import,
        trigger="interval",
        hours=hours,
        id=_JOB_ID,
        next_run_time=first_run_after(120),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=_JOB_ID, interval_hours=hours)
