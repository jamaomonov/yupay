"""Follow accepted CS2 skin trades through Steam's 7-day protection, hourly (plan 3a).

An accepted trade is delivered for us (spec §8.1) but can still be rolled back until
``release_date``. This watch refreshes those trades in batches of 100: released (5)
closes the row; a rollback (6 with ``penalties``) alerts ops and is recorded on the task
(``skin_rollback``) — see ``fulfillment.skin_sweeps``.
"""

from __future__ import annotations

import yupay.api.v1  # noqa: F401  isort: skip

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.skin_sweeps import watch_protected_trades
from yupay.modules.fulfillment.suppliers.waxpeer_trades import WaxpeerTradeClient
from yupay.modules.notifications.alerts import send_admin_alert

log = get_logger("yupay.scheduler.skins_protection_watch")

_JOB_ID = "fulfillment.skins_protection_watch"
_INTERVAL_SECONDS = 3600


async def _alert(text: str) -> None:
    await send_admin_alert(text, kind="skin_trade_rollback")


async def run_skins_protection_watch() -> None:
    """One tick: refresh every accepted, unreleased trade."""
    settings = get_settings()
    if not settings.waxpeer_api_key:
        return
    client = WaxpeerTradeClient(
        api_key=settings.waxpeer_api_key,
        base_url=settings.waxpeer_base_url,
        timeout_seconds=settings.waxpeer_request_timeout_seconds,
    )
    async with get_session_factory()() as session:
        seen = await watch_protected_trades(session, client, alert=_alert)
    log.info("skins_protection_watch.tick", checked=seen)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler."""
    scheduler.add_job(
        run_skins_protection_watch,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("skins_protection_watch.registered", interval_seconds=_INTERVAL_SECONDS)
