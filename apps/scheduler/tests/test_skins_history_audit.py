"""The daily skin history audit: one coalesced job at 04:30 Tashkent, a no-op without a key."""

from __future__ import annotations

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core import config as cfg
from yupay_scheduler.jobs import skins_history_audit
from yupay_scheduler.jobs.skins_history_audit import _JOB_ID, register, run_skins_history_audit


def test_register_adds_one_daily_job_at_half_past_four_tashkent() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    register(scheduler)
    register(scheduler)
    job = scheduler.get_job(_JOB_ID)
    assert job is not None
    assert job.max_instances == 1
    assert job.coalesce is True
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("23", "30")  # 04:30 UTC+5


@pytest.mark.asyncio
async def test_without_a_key_the_tick_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAXPEER_API_KEY", "")
    monkeypatch.setenv("CS2_SKINS_ENABLED", "true")
    cfg.get_settings.cache_clear()

    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("no client without a key")

    monkeypatch.setattr(skins_history_audit, "WaxpeerTradeClient", _boom)
    try:
        await run_skins_history_audit()
    finally:
        cfg.get_settings.cache_clear()
