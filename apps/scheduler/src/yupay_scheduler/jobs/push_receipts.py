"""Read Expo's receipts for pushes sent a while ago (ADR-0102).

A send only says Expo accepted the message; the receipt, ready within about 15 minutes, says
whether Apple or Google took it. ``DeviceNotRegistered`` there disables the device, so the
next push to that account does not go to a removed app. The logic lives in
``push.delivery.check_receipts``; this is the usual thin wrapper.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.push.api import check_receipts

log = get_logger("yupay.scheduler.push_receipts")

_JOB_ID = "push.check_receipts"
_INTERVAL_MINUTES = 15


async def run_push_receipts() -> None:
    """One tick: up to one Expo receipts call's worth of sent messages."""
    factory = get_session_factory()
    async with factory() as session:
        checked = await check_receipts(session)
        await session.commit()
    if checked:
        log.info("push_receipts.tick", checked=checked)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    scheduler.add_job(
        run_push_receipts,
        trigger="interval",
        minutes=_INTERVAL_MINUTES,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
    )
