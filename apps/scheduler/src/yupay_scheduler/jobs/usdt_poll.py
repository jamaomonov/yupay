"""USDT top-up every 20 s: read confirmed transfers, credit them, expire reservations.

ADR-0104. The chain is the source of truth and the journal is keyed by event,
so a missed or failed tick loses nothing: the next one reads from the stored
cursor. What only this job can notice is crediting having **stopped** — any
failure, not just TronGrid being down — while resellers wait. It alerts after
15 minutes without a good poll, and on the conditions that need a person now
(a transfer that failed to ingest, a spam flood), each at most once an hour.
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

log = get_logger("yupay.scheduler.usdt_poll")
_JOB_ID: Final = "usdt_poll"
_INTERVAL_SECONDS: Final = 20
_LAST_OK_KEY: Final = "usdt:poll:last-ok"
_DOWN_AFTER_SECONDS: Final = 15 * 60
_ALERT_TTL_SECONDS: Final = 3600
#: Alerts that would repeat every tick while their cause lasts: once an hour.
_HOURLY: Final = frozenset({"usdt_poll_down", "usdt_ingest_failed", "usdt_poll_flood"})


async def run_usdt_poll() -> None:
    """One tick. Never raises: a failure is logged by class and checked for the down alert."""
    t = now()
    try:
        ok = await _tick()
    except Exception as exc:  # noqa: BLE001 - logged by class; the next tick retries
        log.error("usdt_poll.failed", error=type(exc).__name__)  # noqa: TRY400
        ok = False
    try:
        if ok:
            await get_redis().set(_LAST_OK_KEY, str(int(t.timestamp())))
        else:
            await _maybe_alert_down(int(t.timestamp()))
    except Exception as exc:  # noqa: BLE001 - alerting must not crash the job
        log.error("usdt_poll.alert_failed", error=type(exc).__name__)  # noqa: TRY400


async def _tick() -> bool:
    """Sweep, poll, send alerts. True when the poll itself succeeded."""
    sessions = get_session_factory()
    t = now()
    async with sessions() as db:
        swept = await sweep(db, now_=t)
        await db.commit()
    if swept.expired or swept.released:
        log.info("usdt_poll.swept", expired=swept.expired, released=swept.released)
    result = await poll_once(sessions, now_=t)
    if result.unavailable:
        log.warning("usdt_poll.chain_unavailable", networks=result.unavailable)
    alerts = list(result.alerts)
    if result.truncated:
        alerts.append(
            (
                "usdt_poll_flood",
                f"USDT ({', '.join(n.upper() for n in result.truncated)}): переводов больше, "
                "чем читается за один проход (спам или долгий простой) — зачисление может отставать",
            )
        )
    for kind, text in alerts:
        await _send(kind, text)
    return not result.failed and not result.unavailable


async def _send(kind: str, text: str) -> None:
    if kind in _HOURLY:
        redis = get_redis()
        key = f"usdt:alert:{kind}"
        if not await redis.set(key, "1", nx=True, ex=_ALERT_TTL_SECONDS):
            return
        if not await send_admin_alert(text, kind=kind):
            await redis.delete(key)
        return
    await send_admin_alert(text, kind=kind)


async def _maybe_alert_down(now_s: int) -> None:
    """Alert when no poll has succeeded for 15 min while a reseller is waiting."""
    last = await get_redis().get(_LAST_OK_KEY)
    if last is not None and now_s - int(last) < _DOWN_AFTER_SECONDS:
        return
    async with get_session_factory()() as db:
        waiting = await db.scalar(
            select(func.count())
            .select_from(UsdtReservation)
            .where(UsdtReservation.holds_amount.is_(True))
        )
    if waiting:
        await _send(
            "usdt_poll_down",
            "USDT: зачисление не работает больше 15 минут, а пополнения ждут — "
            "смотрите usdt_poll / usdt.chain_unavailable в логах планировщика",
        )


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
