"""Hourly supplier-catalog watchdog: delisted positions come off the shelf.

Runs a few minutes after ``sync_supplier_catalog`` on the same cadence, so a
tick that alerts is looking at the same supplier state the price refresh just
consumed. The two-strike logic (stamp, then deactivate + Telegram) lives in
``yupay.modules.integrations.catalog_watch`` — this file only gives it a
session, the real G2B client and the real alert sender.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.integrations.catalog_watch import watch_mapped_variants
from yupay.modules.notifications.alerts import send_admin_alert

from yupay_scheduler.startup import first_run_after

log = get_logger("yupay.scheduler.catalog_watch")

_JOB_ID = "integrations.catalog_watch"


async def run_catalog_watch() -> None:
    """One tick. Never raises: a supplier outage must not stop the scheduler."""
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

    fulfiller = REGISTRY.get("g2b")
    if not isinstance(fulfiller, G2bFulfiller) or not fulfiller.available:
        log.info("integrations.catalog_watch.tick", supplier="g2b", skipped="no client")
        return

    factory = get_session_factory()
    try:
        async with factory() as session:
            report = await watch_mapped_variants(
                session,
                client=fulfiller._client(),
                send_alert=send_admin_alert,
                supplier_slug="g2b",
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 -- log and wait for the next tick
        log.warning("integrations.catalog_watch.tick_failed", error=str(exc)[:200])
        return
    log.info(
        "integrations.catalog_watch.tick",
        supplier="g2b",
        checked=report.checked,
        stamped=report.stamped,
        deactivated=report.deactivated,
        reappeared=report.reappeared,
        skipped_games=report.skipped_games,
    )


def register(scheduler: AsyncIOScheduler) -> None:
    minutes = max(1, int(get_settings().price_refresh_interval_minutes))
    scheduler.add_job(
        run_catalog_watch,
        trigger="interval",
        minutes=minutes,
        id=_JOB_ID,
        # After sync (+60s) and the price refresh (+90s): the watch should see
        # the catalogue state those two just acted on, not race them.
        next_run_time=first_run_after(180),
    )
    log.info("scheduler.job_registered", job_id=_JOB_ID, interval_minutes=minutes)
