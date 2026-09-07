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


async def test_the_merchant_machine_api_is_exempt(limited_client: AsyncClient) -> None:
    """``/merchant/v1`` must never answer the coarse limiter's 429.

    Behavioural, not configurational: the limiter is off under
    ``ENVIRONMENT=test``, so a test that only asserts the settings would pass
    with the exemption deleted. Here the limit is 3/minute and live — proved by
    ``test_request_over_limit_gets_429`` against the same fixture — and these
    calls still all reach the auth dependency.

    Why it matters: both tiers are 600/60 s in production, ``limits`` allows
    ``count <= limit`` where ``ip_guard.hit_counter`` returns ``count > limit``,
    and ``SlowAPIMiddleware`` runs before any dependency — so a caller
    concentrated on one endpoint (which is what the module README tells
    resellers to do with ``/catalog``: poll it, there are no price webhooks)
    would have got slowapi's handler body instead of ours. That body has no
    ``type`` and no ``code``, on a contract we published to third parties.

    Enumerated from the app so a Task 4/5 endpoint is covered the day it is
    written — ``_exempt_self_authenticating_routes`` walks the same router.
    """
    import re

    from fastapi.routing import APIRoute
    from yupay.bootstrap import create_app

    routes = [
        (
            next(m for m in ("GET", "POST", "PATCH", "PUT", "DELETE") if m in route.methods),
            route.path,
        )
        for route in create_app().routes
        if isinstance(route, APIRoute) and route.path.startswith("/merchant/v1")
    ]
    assert routes, "no /merchant/v1 routes found — the enumeration is wrong"

    for method, path in routes:
        for _ in range(10):
            r = await limited_client.request(method, re.sub(r"\{[^}]+\}", "placeholder", path))
            # The dependency's own 401, in problem+json with a `code` —
            # never slowapi's `{"error": "Rate limit exceeded: ..."}`.
            assert r.status_code == 401, f"{method} {path}: {r.status_code} {r.text}"
            assert r.json()["code"] == "missing_credentials", f"{method} {path}: {r.text}"
