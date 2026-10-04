"""P2P housekeeping every 30 s: expire overdue top-ups, end quarantine, notice silence.

Correctness does not depend on this tick — the webhook and the cabinet read
both treat an overdue ``pending`` as expired — so a missed tick only delays
the release of a quarantined amount. The silence alert is the one thing only
this job can see: reservations expiring while @HUMOcardbot has said nothing
for hours means the Business bot is disconnected, not that nobody paid.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select

from yupay.core.clock import now
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.notifications.alerts import send_admin_alert
from yupay.modules.p2p.models import P2PIncoming, P2PReservation
from yupay.modules.p2p.reservations import sweep

log = get_logger("yupay.scheduler.p2p_sweep")
_JOB_ID: Final = "p2p_sweep"
_INTERVAL_SECONDS: Final = 30
SILENCE: Final = timedelta(hours=6)
_EXPIRED_LOOKBACK: Final = timedelta(minutes=2)
_ALERT_KEY: Final = "p2p:silence-alert"
_ALERT_TTL_SECONDS: Final = 3600


def silence_alert_due(last_incoming_at: datetime | None, expired_now: int, now_: datetime) -> bool:
    """Whether expiring reservations coincide with a silent HUMO feed.

    Args:
        last_incoming_at: Timestamp of the last @HUMOcardbot notification received, or None.
        expired_now: Count of reservations that expired in this sweep.
        now_: Current time.

    Returns:
        True if reservations expired and the HUMO bot has been silent for >6 hours.
    """
    if expired_now <= 0:
        return False
    return last_incoming_at is None or now_ - last_incoming_at > SILENCE


async def run_p2p_sweep() -> None:
    """One tick: expire pending reservations, end quarantine, alert on silence."""
    t = now()
    async with get_session_factory()() as db:
        result = await sweep(db, now_=t)
        last = await db.scalar(select(func.max(P2PIncoming.received_at)))
        # Count recently-expired rows (those expired in the last 2 minutes) to catch
        # both this tick's expirations and those from the cabinet's read() in-place path.
        recently_expired = await db.scalar(
            select(func.count(P2PReservation.id)).where(
                P2PReservation.status == "expired",
                P2PReservation.closed_at > t - _EXPIRED_LOOKBACK,
                P2PReservation.closed_at <= t,
            )
        )
        await db.commit()
    if result.expired or result.released:
        log.info("p2p_sweep.tick", expired=result.expired, released=result.released)
    if silence_alert_due(last, recently_expired or 0, t):
        redis = get_redis()
        if await redis.set(_ALERT_KEY, "1", nx=True, ex=_ALERT_TTL_SECONDS):
            await send_admin_alert(
                "P2P: резервы истекают, а от HUMO нет уведомлений больше 6 часов — проверьте бота",
                kind="p2p_silence",
            )


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job. Safe to call once at startup."""
    scheduler.add_job(
        run_p2p_sweep,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("p2p_sweep.registered", interval_seconds=_INTERVAL_SECONDS)


__all__ = ["SILENCE", "now", "register", "run_p2p_sweep", "send_admin_alert", "silence_alert_due"]
