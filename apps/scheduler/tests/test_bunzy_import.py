"""The Bunzy import job: off by default, and one session per article."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core import config as cfg
from yupay_scheduler.jobs.bunzy_import import _JOB_ID, register, run_bunzy_import


@pytest.fixture
def _with_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BUNZY_API_KEY", "sk_test_key")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def test_without_a_key_the_job_is_not_registered_at_all() -> None:
    # Dev and CI have no key. Registering a job that would 401 every hour
    # buys nothing but a log full of failures.
    cfg.get_settings.cache_clear()
    scheduler = AsyncIOScheduler()
    register(scheduler)
    assert scheduler.get_job(_JOB_ID) is None


@pytest.mark.usefixtures("_with_key")
def test_register_adds_one_coalesced_job_that_runs_soon_after_boot() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    register(scheduler)
    register(scheduler)

    job = scheduler.get_job(_JOB_ID)
    assert job is not None
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.next_run_time is not None
    assert job.next_run_time - datetime.now(UTC) <= timedelta(minutes=5)


async def test_running_without_a_key_touches_nothing() -> None:
    cfg.get_settings.cache_clear()
    await run_bunzy_import()
