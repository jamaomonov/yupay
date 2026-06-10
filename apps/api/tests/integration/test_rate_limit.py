"""Global per-IP rate limiting (slowapi) — AGENTS.md §9.

Disabled under ``ENVIRONMENT=test`` unless ``RATE_LIMIT_ENABLED=true`` is set
explicitly, so the rest of the suite can hammer the ASGI app freely.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from yupay.core import config as cfg

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def limited_client(db_engine, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """An app with rate limiting forced on and a tiny limit."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from yupay.bootstrap import create_app
    from yupay.core import db as core_db
    from yupay.core import redis as core_redis

    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "3/minute")
    cfg.get_settings.cache_clear()

    core_db._engine = db_engine  # type: ignore[attr-defined]
    core_db._session_factory = async_sessionmaker(  # type: ignore[attr-defined]
        bind=db_engine, expire_on_commit=False
    )
    core_redis._client = None  # type: ignore[attr-defined]

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    core_db._engine = None  # type: ignore[attr-defined]
    core_db._session_factory = None  # type: ignore[attr-defined]
    await core_redis.close_redis()
    cfg.get_settings.cache_clear()


async def test_request_over_limit_gets_429(limited_client: AsyncClient) -> None:
    for _ in range(3):
        r = await limited_client.get("/api/v1/payments/providers")
        assert r.status_code == 200, r.text
    r = await limited_client.get("/api/v1/payments/providers")
    assert r.status_code == 429, r.text


async def test_health_probes_are_exempt(limited_client: AsyncClient) -> None:
    for _ in range(10):
        r = await limited_client.get("/healthz")
        assert r.status_code == 200
        r = await limited_client.get("/readyz")
        assert r.status_code == 200


async def test_rate_limit_off_by_default_in_tests(integration_client: AsyncClient) -> None:
    """The regular test app (no explicit opt-in) must not throttle the suite."""
    for _ in range(10):
        r = await integration_client.get("/api/v1/payments/providers")
        assert r.status_code == 200
