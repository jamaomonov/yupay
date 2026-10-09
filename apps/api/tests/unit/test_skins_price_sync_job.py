"""The five-minute job logs a failed tick of any kind and never raises."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from yupay.core import config as cfg

pytestmark = pytest.mark.asyncio


async def test_a_database_error_is_logged_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    from yupay_scheduler.jobs import skins_price_sync as job

    monkeypatch.setenv("CS2_SKINS_SYNC_ENABLED", "true")
    monkeypatch.setenv("WAXPEER_API_KEY", "k")
    cfg.get_settings.cache_clear()

    async def boom(*_: object, **__: object) -> None:
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    events: list[str] = []
    monkeypatch.setattr(job, "sync_prices", boom)
    monkeypatch.setattr(job, "get_session_factory", lambda: None)
    monkeypatch.setattr(job, "get_redis", lambda: None)
    monkeypatch.setattr(job.log, "warning", lambda event, **_: events.append(event))
    monkeypatch.setattr(job.log, "exception", lambda event, **_: events.append(event))
    await job.run_skins_price_sync()
    assert events == ["skins.prices.failed"]
    cfg.get_settings.cache_clear()


async def test_csmarket_source_runs_the_csmarket_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    from yupay_scheduler.jobs import skins_price_sync as job

    monkeypatch.setenv("CS2_SKINS_SYNC_ENABLED", "true")
    monkeypatch.setenv("CS2_SKINS_SOURCE", "csmarket")
    monkeypatch.setenv("CSMARKET_API_KEY", "csm_test")
    cfg.get_settings.cache_clear()
    called: list[str] = []

    async def waxpeer(*_: object, **__: object) -> None:
        called.append("waxpeer")

    async def csmarket(*_: object, **__: object) -> None:
        called.append("csmarket")

    monkeypatch.setattr(job, "sync_prices", waxpeer)
    monkeypatch.setattr(job, "sync_prices_csmarket", csmarket)
    monkeypatch.setattr(job, "get_session_factory", lambda: None)
    monkeypatch.setattr(job, "get_redis", lambda: None)
    await job.run_skins_price_sync()
    assert called == ["csmarket"]
    cfg.get_settings.cache_clear()


async def test_csmarket_failure_is_logged_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    from yupay.modules.fulfillment.suppliers.csmarket_client import CsmarketUnavailableError
    from yupay_scheduler.jobs import skins_price_sync as job

    monkeypatch.setenv("CS2_SKINS_SYNC_ENABLED", "true")
    monkeypatch.setenv("CS2_SKINS_SOURCE", "csmarket")
    monkeypatch.setenv("CSMARKET_API_KEY", "csm_test")
    cfg.get_settings.cache_clear()

    async def down(*_: object, **__: object) -> None:
        raise CsmarketUnavailableError("HTTP 502")

    events: list[str] = []
    monkeypatch.setattr(job, "sync_prices_csmarket", down)
    monkeypatch.setattr(job, "get_session_factory", lambda: None)
    monkeypatch.setattr(job, "get_redis", lambda: None)
    monkeypatch.setattr(job.log, "warning", lambda event, **_: events.append(event))
    await job.run_skins_price_sync()
    assert events == ["skins.prices.failed"]
    cfg.get_settings.cache_clear()
