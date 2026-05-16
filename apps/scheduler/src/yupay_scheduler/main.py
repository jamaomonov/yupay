"""Scheduler entrypoint.

Run as: ``python -m yupay_scheduler.main``.
"""

from __future__ import annotations

import asyncio
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.logging import configure_logging, get_logger

configure_logging()
log = get_logger("yupay.scheduler")


def build_scheduler() -> AsyncIOScheduler:
    """Build the AsyncIO scheduler with no jobs registered yet.

    Jobs are added by importing the corresponding module from ``yupay_scheduler.jobs``.
    """
    return AsyncIOScheduler(timezone="UTC")


async def run() -> None:
    """Start the scheduler and block until SIGINT/SIGTERM."""
    scheduler = build_scheduler()
    scheduler.start()
    log.info("scheduler.started")

    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    scheduler.shutdown(wait=True)
    log.info("scheduler.stopped")


if __name__ == "__main__":
    asyncio.run(run())
