"""Accrue and mature affiliate commission.

Two steps in one tick, in one transaction: accrue what is newly delivered, then
release what has finished its hold period. Both are idempotent, so a tick that
dies halfway costs nothing but a retry.

Five minutes rather than on-delivery. Commission sits behind a two-week hold
before a partner can withdraw it, so freshness is worth almost nothing here —
and the fulfilment path it would otherwise hang off is the slowest in the
system, the one where a customer is waiting for a code.

Reaches into ``affiliate.api``, which deliberately imports no router, so this
process does not load the FastAPI route stack to move a few decimals around.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.affiliate import api as affiliate_api

from yupay_scheduler.startup import first_run_after

log = get_logger("yupay.scheduler.affiliate_accrual")

_JOB_ID = "affiliate.accrual"


async def run_affiliate_accrual() -> None:
    """One scheduler tick, in its own session/transaction."""
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session, session.begin():
        accrued = await affiliate_api.accrue_commissions(
            session,
            hold_days=settings.affiliate_hold_days,
            limit=settings.affiliate_sweep_batch,
        )
        matured = await affiliate_api.mature_commissions(
            session, limit=settings.affiliate_sweep_batch
        )
    if accrued or matured:
        log.info("affiliate.accrual.tick", accrued=accrued, matured=matured)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to ``scheduler``."""
    minutes = max(1, int(get_settings().affiliate_sweep_minutes))
    scheduler.add_job(
        run_affiliate_accrual,
        trigger="interval",
        minutes=minutes,
        id=_JOB_ID,
        # Explicit first run: without it the first tick is a whole interval
        # after boot, and a container restarting more often than its own period
        # never runs the job at all. Offset so it does not land together with
        # the other sweeps on every deploy.
        next_run_time=first_run_after(90),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("affiliate.accrual.registered", interval_minutes=minutes)


__all__ = ["register", "run_affiliate_accrual"]
