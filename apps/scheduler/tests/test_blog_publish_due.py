"""The due-publish job must register once and never share a session."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay_scheduler.jobs.blog_publish_due import _JOB_ID, register


def test_register_adds_one_coalesced_job() -> None:
    scheduler = AsyncIOScheduler()
    register(scheduler)
    register(scheduler)
    job = scheduler.get_job(_JOB_ID)
    assert job is not None
    assert job.max_instances == 1
    assert job.coalesce is True
