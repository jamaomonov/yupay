"""USDT top-up every 20 s: read confirmed transfers, credit them, expire reservations.

ADR-0104. The chain is the source of truth and the journal is keyed by
transaction id, so a missed or failed tick loses nothing: the next one reads
from the stored cursor minus ten minutes. What only this job can notice is
TronGrid being down while resellers wait — alerted at most once an hour.
"""

from __future__ import annotations

from typing import Final

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select
from yupay.core.clock import now
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.notifications.alerts import send_admin_alert
from yupay.modules.usdt.models import UsdtReservation
from yupay.modules.usdt.poll import poll_once
from yupay.modules.usdt.reservations import sweep
from yupay.modules.usdt.tron import TronUnavailableError

log = get_logger("yupay.scheduler.usdt_poll")
_JOB_ID: Final = "usdt_poll"
_INTERVAL_SECONDS: Final = 20
_LAST_OK_KEY: Final = "usdt:poll:last-ok"
_DOWN_ALERT_KEY: Final = "usdt:poll:down-alert"
_DOWN_AFTER_SECONDS: Final = 15 * 60
_ALERT_TTL_SECONDS: Final = 3600


async def run_usdt_poll() -> None:
    """One tick. Failures are logged by class only and swallowed; the next tick retries."""
    try:
        await _tick()
    except Exception as exc:  # noqa: BLE001 - logged by class; the next tick retries
        log.error("usdt_poll.failed", error=type(exc).__name__)  # noqa: TRY400


async def _tick() -> None:
    sessions = get_session_factory()
    t = now()
    async with sessions() as db:
        swept = await sweep(db, now_=t)
        await db.commit()
    if swept.expired or swept.released:
        log.info("usdt_poll.swept", expired=swept.expired, released=swept.released)
    redis = get_redis()
    try:
        result = await poll_once(sessions, now_=t)
    except TronUnavailableError as exc:
        log.warning("usdt_poll.tron_unavailable", reason=str(exc))
        await _maybe_alert_down(int(t.timestamp()))
        return
    await redis.set(_LAST_OK_KEY, str(int(t.timestamp())))
    for kind, text in result.alerts:
        await send_admin_alert(text, kind=kind)


async def _maybe_alert_down(now_s: int) -> None:
    """Alert when TronGrid has failed for 15 min while a reseller is waiting."""
    redis = get_redis()
    last = await redis.get(_LAST_OK_KEY)
    if last is not None and now_s - int(last) < _DOWN_AFTER_SECONDS:
        return
    async with get_session_factory()() as db:
        waiting = await db.scalar(
            select(func.count())
            .select_from(UsdtReservation)
            .where(UsdtReservation.status == "pending")
        )
    if not waiting:
        return
    if not await redis.set(_DOWN_ALERT_KEY, "1", nx=True, ex=_ALERT_TTL_SECONDS):
        return
    if not await send_admin_alert(
        "USDT: TronGrid не отвечает больше 15 минут, а пополнения ждут — зачисление задерживается",
        kind="usdt_poll_down",
    ):
        await redis.delete(_DOWN_ALERT_KEY)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job. Safe to call once at startup."""
    scheduler.add_job(
        run_usdt_poll,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("usdt_poll.registered", interval_seconds=_INTERVAL_SECONDS)


__all__ = ["register", "run_usdt_poll"]
