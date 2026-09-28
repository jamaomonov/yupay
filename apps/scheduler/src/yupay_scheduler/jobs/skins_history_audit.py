"""Compare the last 14 days of settled CS2 skin trades with Waxpeer, daily (plan 4).

Spec §6.5: a trade can still change on Waxpeer's side after we called it settled — a late
rollback after release, or a skin that went out on an order we refunded. The audit reads
our settled trades back by ``project_id`` and alerts ops on every divergence; it writes
nothing (``fulfillment.skin_sweeps.audit_recent_trades``). 04:30 Tashkent — after the
night's orders, before the working day.
"""

from __future__ import annotations

import yupay.api.v1  # noqa: F401  isort: skip

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.skin_sweeps import audit_recent_trades
from yupay.modules.fulfillment.suppliers.waxpeer_trades import WaxpeerTradeClient
from yupay.modules.notifications.alerts import send_admin_alert

log = get_logger("yupay.scheduler.skins_history_audit")

_JOB_ID = "fulfillment.skins_history_audit"
# The scheduler runs in UTC; Tashkent is UTC+5 all year.
_HOUR_UTC = 23
_MINUTE = 30


async def _alert(text: str) -> None:
    await send_admin_alert(text, kind="skin_history_divergence")


async def run_skins_history_audit() -> None:
    """One tick: read the last 14 days of settled trades back from Waxpeer."""
    settings = get_settings()
    if not settings.waxpeer_api_key or not settings.cs2_skins_enabled:
        return
    client = WaxpeerTradeClient(
        api_key=settings.waxpeer_api_key,
        base_url=settings.waxpeer_base_url,
        timeout_seconds=settings.waxpeer_request_timeout_seconds,
    )
    async with get_session_factory()() as session:
        diverged = await audit_recent_trades(session, client, alert=_alert)
    log.info("skins_history_audit.tick", diverged=diverged)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the daily job to a running scheduler. Safe to call more than once."""
    scheduler.add_job(
        run_skins_history_audit,
        trigger="cron",
        hour=_HOUR_UTC,
        minute=_MINUTE,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("skins_history_audit.registered", hour_utc=_HOUR_UTC, minute=_MINUTE)


__all__ = ["register", "run_skins_history_audit"]
