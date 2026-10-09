"""Five-minute fold of the skins source onto ``skin_items`` (ADR-0093, ADR-0098).

``cs2_skins_source`` picks the source: Waxpeer's CSV snapshot (~240 MB, ~10 s) or the
csmarket feed (~15 000 items in 16 pages, a few seconds). Either way only rows whose
prices moved are written. Skipped while ``cs2_skins_sync_enabled`` is off or the chosen
source has no key. ``max_instances=1`` and ``coalesce=True``: a slow tick must never
be joined by the next one.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.fulfillment.suppliers.csmarket_client import (
    CsmarketClient,
    CsmarketError,
    CsmarketUnavailableError,
)
from yupay.modules.fulfillment.suppliers.waxpeer_client import (
    WaxpeerClient,
    WaxpeerError,
    WaxpeerUnavailableError,
)
from yupay.modules.skins.prices import sync_prices
from yupay.modules.skins.prices_csmarket import sync_prices_csmarket

from yupay_scheduler.startup import first_run_after

log = get_logger("yupay.scheduler.skins_price_sync")

_JOB_ID = "skins.price_sync"


async def run_skins_price_sync() -> None:
    """One tick. A supplier failure is logged and the previous prices stand."""
    settings = get_settings()
    if settings.cs2_skins_source == "csmarket":
        await _run_csmarket()
        return
    if not settings.cs2_skins_sync_enabled or not settings.waxpeer_api_key:
        log.info("skins.prices.skipped", reason="sync disabled or no waxpeer key")
        return
    client = WaxpeerClient(
        api_key=settings.waxpeer_api_key,
        base_url=settings.waxpeer_base_url,
        timeout_seconds=settings.waxpeer_request_timeout_seconds,
    )
    try:
        await sync_prices(get_session_factory(), client, get_redis())
    except (WaxpeerError, WaxpeerUnavailableError) as exc:
        log.warning("skins.prices.failed", error=str(exc)[:200])
    except Exception as exc:
        log.exception("skins.prices.failed", error=str(exc)[:200])


async def _run_csmarket() -> None:
    settings = get_settings()
    if not settings.cs2_skins_sync_enabled or not settings.csmarket_api_key:
        log.info("skins.prices.skipped", reason="sync disabled or no csmarket key")
        return
    client = CsmarketClient(
        api_key=settings.csmarket_api_key,
        base_url=settings.csmarket_base_url,
        timeout_seconds=settings.csmarket_request_timeout_seconds,
    )
    try:
        await sync_prices_csmarket(get_session_factory(), client, get_redis())
    except (CsmarketError, CsmarketUnavailableError) as exc:
        log.warning("skins.prices.failed", source="csmarket", error=str(exc)[:200])
    except Exception as exc:
        log.exception("skins.prices.failed", source="csmarket", error=str(exc)[:200])


def register(scheduler: AsyncIOScheduler) -> None:
    minutes = max(1, int(get_settings().skins_snapshot_interval_minutes))
    scheduler.add_job(
        run_skins_price_sync,
        trigger="interval",
        minutes=minutes,
        id=_JOB_ID,
        next_run_time=first_run_after(60),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=_JOB_ID, interval_minutes=minutes)
