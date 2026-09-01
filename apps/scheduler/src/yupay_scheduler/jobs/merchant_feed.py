"""Hourly Google Merchant Center feed sync.

Runs after the price refresh on the same cadence, so the prices Google shows
are the prices that tick just wrote. A no-op (logged, not silent) until the
three MERCHANT_CENTER_* settings are present — see ADR-0065 and
docs/runbooks/merchant-feed.md.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.integrations.merchant_feed import build_client, sync_merchant_feed

from yupay_scheduler.startup import first_run_after

log = get_logger("yupay.scheduler.merchant_feed")

_JOB_ID = "integrations.merchant_feed"


async def run_merchant_feed() -> None:
    """One tick. Never raises: a Google outage must not stop the scheduler."""
    settings = get_settings()
    client = build_client(settings)
    if client is None:
        log.info("integrations.merchant_feed.tick", skipped="not configured")
        return

    base_url = settings.web_base_url or "https://yupay.uz"
    try:
        factory = get_session_factory()
        async with factory() as session:
            report = await sync_merchant_feed(session, client=client, base_url=base_url)
    except Exception as exc:  # noqa: BLE001 -- log and wait for the next tick
        log.warning("integrations.merchant_feed.tick_failed", error=str(exc)[:200])
        return
    finally:
        await client.aclose()
    log.info(
        "integrations.merchant_feed.tick",
        desired=report.desired,
        upserted=report.upserted,
        deleted=report.deleted,
        skipped=report.skipped,
        errors=report.errors,
    )


def register(scheduler: AsyncIOScheduler) -> None:
    minutes = max(1, int(get_settings().price_refresh_interval_minutes))
    scheduler.add_job(
        run_merchant_feed,
        trigger="interval",
        minutes=minutes,
        id=_JOB_ID,
        # After sync (+60s), price refresh (+90s) and the catalog watch (+180s):
        # the feed should carry the prices and deactivations those just wrote.
        next_run_time=first_run_after(300),
    )
    log.info("scheduler.job_registered", job_id=_JOB_ID, interval_minutes=minutes)
