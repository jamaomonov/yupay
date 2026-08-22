"""A long-period job must not wait a whole period for its first run.

APScheduler's ``interval`` trigger with no ``next_run_time`` fires first one
whole interval after registration. For the hourly price refresh that means
every restart pushes it an hour out, so a container restarting more often than
that never runs it — while the scheduler is up and the job reads as
registered. The daily evidence purge needs only one restart a day to never
happen at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay_scheduler.jobs import (
    fx_refresh,
    purge_evidence,
    refresh_supplier_prices,
    refresh_voucher_stock,
)

#: Every job whose period is long enough that losing one costs a real window.
LONG_PERIOD_JOBS = [
    refresh_supplier_prices,
    refresh_voucher_stock,
    purge_evidence,
    fx_refresh,
]


@pytest.mark.parametrize("module", LONG_PERIOD_JOBS, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_the_first_run_comes_soon_after_boot(module: object) -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    module.register(scheduler)  # type: ignore[attr-defined]

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.next_run_time is not None, "no next_run_time — first run is a whole period away"

    waits = job.next_run_time - datetime.now(UTC)
    assert waits <= timedelta(minutes=5), (
        f"{job.id} first runs in {waits}; a restart inside that window loses the run entirely"
    )
    assert waits > timedelta(seconds=0), "a crash-looping container would re-run it every attempt"


def test_the_stagger_keeps_them_off_each_other() -> None:
    """They share supplier APIs; a deploy should not fire them all at once."""
    scheduler = AsyncIOScheduler(timezone="UTC")
    for module in LONG_PERIOD_JOBS:
        module.register(scheduler)  # type: ignore[attr-defined]

    starts = sorted(job.next_run_time for job in scheduler.get_jobs())
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    assert all(gap >= timedelta(seconds=15) for gap in gaps), f"too tight: {gaps}"
