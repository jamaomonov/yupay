"""UzQR every 5 s: book paid QR invoices, close the ones nobody may pay (ADR-0106).

UzQR never calls us back, so a QR payment is booked by this job or not at all.
The spec asks for a status read every 3 s while the payer waits; 5 s keeps the
wait short without doubling the calls. ``max_instances=1`` with ``coalesce``
means a slow UzQR stretches a tick instead of stacking them.

What only this job can notice is booking having **stopped** while invoices are
open. It alerts once an hour after 10 minutes without a tick in which UzQR
answered every call.
"""

from __future__ import annotations

from typing import Final

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.clock import now
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.notifications.alerts import send_admin_alert
from yupay.modules.payments.gateways import REGISTRY
from yupay.modules.uzqr.poll import open_count, poll_once

log = get_logger("yupay.scheduler.uzqr_poll")
_JOB_ID: Final = "uzqr_poll"
_INTERVAL_SECONDS: Final = 5
_LAST_OK_KEY: Final = "uzqr:poll:last-ok"
_DOWN_AFTER_SECONDS: Final = 10 * 60
_ALERT_KEY: Final = "uzqr:alert:poll_down"
_ALERT_TTL_SECONDS: Final = 3600


async def run_uzqr_poll() -> None:
    """One tick. Never raises: a failure is logged by class and checked for the alert."""
    if not REGISTRY["uzqr"].available:
        return
    t = int(now().timestamp())
    try:
        result = await poll_once(get_session_factory())
        ok = result.unavailable == 0
    except Exception as exc:  # noqa: BLE001 - logged by class; the next tick retries
        log.error("uzqr_poll.failed", error=type(exc).__name__)  # noqa: TRY400
        ok = False
    try:
        if ok:
            await get_redis().set(_LAST_OK_KEY, str(t))
        else:
            await _maybe_alert_down(t)
    except Exception as exc:  # noqa: BLE001 - alerting must not crash the job
        log.error("uzqr_poll.alert_failed", error=type(exc).__name__)  # noqa: TRY400


async def _maybe_alert_down(now_s: int) -> None:
    redis = get_redis()
    last = await redis.get(_LAST_OK_KEY)
    if last is not None and now_s - int(last) < _DOWN_AFTER_SECONDS:
        return
    async with get_session_factory()() as db:
        waiting = await open_count(db)
    if not waiting:
        return
    if not await redis.set(_ALERT_KEY, "1", nx=True, ex=_ALERT_TTL_SECONDS):
        return
    sent = await send_admin_alert(
        f"UzQR: оплаты по QR не проверяются больше 10 минут, открытых счетов: {waiting}. "
        "Смотрите uzqr.poll / uzqr_poll в логах планировщика (docs/runbooks/uzqr.md)",
        kind="uzqr_poll_down",
    )
    if not sent:
        await redis.delete(_ALERT_KEY)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job. Safe to call once at startup."""
    scheduler.add_job(
        run_uzqr_poll,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("uzqr_poll.registered", interval_seconds=_INTERVAL_SECONDS)


__all__ = ["register", "run_uzqr_poll"]
