"""The global limiter: what it counts, and what it says when it refuses.

Two properties are asserted here because both were wrong in ways that only
show up under a crowd, which is exactly when nobody is reading logs.

1. A bucket must belong to a *route*, not to a URL. slowapi's default
   ``key_style="url"`` gives ``/orders/aaa`` and ``/orders/bbb`` separate
   budgets, which means anything with a path parameter is effectively
   unlimited while the fixed-path endpoints every session touches carry the
   whole load. It also makes key cardinality grow as IPs x distinct URLs.

2. A 429 must reach the browser. ``SlowAPIMiddleware`` short-circuits, so if
   it sits outside CORS its response never passes through the CORS layer, the
   browser blocks it, and the client sees a network failure rather than "slow
   down" -- and then retries, multiplying the traffic that was already over
   the line.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from yupay.core import config as cfg

pytestmark = pytest.mark.integration

ORIGIN = "https://yupay.uz"


@pytest.fixture
async def limited_client(monkeypatch: pytest.MonkeyPatch):
    """An app whose global limit trips after two requests."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "2/minute")
    # list[str] setting: pydantic-settings parses complex types as JSON.
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", f'["{ORIGIN}"]')
    cfg.get_settings.cache_clear()

    from yupay.bootstrap import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    cfg.get_settings.cache_clear()


async def test_two_urls_of_one_route_share_a_budget(limited_client) -> None:
    """The bucket is the route. Otherwise a caller sweeping distinct ids never
    trips the limit, and ADR-0028's "outer circuit breaker" does not exist for
    any route carrying a path parameter."""
    statuses = []
    for oid in ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"):
        for _ in range(2):
            r = await limited_client.get(f"/api/v1/orders/{oid}")
            statuses.append(r.status_code)

    assert 429 in statuses, (
        "four requests against one route with a 2/minute limit must trip it, "
        f"whatever ids they carry; got {statuses}"
    )


async def test_a_429_carries_the_cors_header(limited_client) -> None:
    """Without this the browser blocks the response and the client cannot tell
    throttling from an outage -- so it retries, four times over."""
    last = None
    for _ in range(5):
        last = await limited_client.get("/api/v1/catalog/brands", headers={"Origin": ORIGIN})
        if last.status_code == 429:
            break

    assert last is not None
    assert last.status_code == 429, "the limit should have tripped within five requests"
    assert last.headers.get("access-control-allow-origin") == ORIGIN, (
        "a 429 without the CORS header is invisible to the browser: fetch rejects "
        "as a network error and the client retries instead of backing off"
    )


# --- provider callbacks must never be throttled ------------------------------

# (path, json body) for one call per provider surface. The bodies are
# deliberately unauthenticated: what is asserted is the *absence of 429*, not
# the business outcome, so a 401/400 from the signature check is a pass.
_CALLBACKS = [
    ("/api/v1/webhooks/g2b/not-the-secret", {}),
    ("/api/v1/payments/payme/merchant", {"method": "CheckPerformTransaction", "params": {}}),
    ("/api/v1/payments/uzum/check", {}),
    ("/api/v1/payments/uzum/create", {}),
    ("/api/v1/payments/uzum/confirm", {}),
    ("/api/v1/payments/uzum/reverse", {}),
    ("/api/v1/payments/uzum/status", {}),
]


@pytest.mark.parametrize(("path", "body"), _CALLBACKS)
async def test_provider_callbacks_are_never_rate_limited(limited_client, path, body) -> None:
    """A 429 to an acquirer or a supplier costs money, not safety.

    G2B fires each callback once with a single retry, so a throttled one is a
    delivery notification lost for good. Payme reads a 429 as a transport
    failure and retries, which produces more 429s. These routes are already
    gated by signature, Basic auth or a path secret — and Payme additionally by
    an IP allowlist at Caddy — so the per-IP limit adds no security here.
    """
    statuses = []
    for _ in range(6):  # limit is 2/minute in this fixture
        r = await limited_client.post(path, json=body)
        statuses.append(r.status_code)

    assert 429 not in statuses, f"{path} was throttled: {statuses}"


async def test_click_callbacks_are_never_rate_limited(limited_client) -> None:
    """Click posts form-encoded, not JSON — same rule, different content type."""
    for path in ("/api/v1/payments/click/prepare", "/api/v1/payments/click/complete"):
        statuses = []
        for _ in range(6):
            r = await limited_client.post(path, data={"click_trans_id": "1"})
            statuses.append(r.status_code)
        assert 429 not in statuses, f"{path} was throttled: {statuses}"


# --- the coarse net, and what it does not police --------------------------


async def test_the_global_limit_is_a_flood_stopper_not_a_policy() -> None:
    """The 120/minute default was sized for endpoints that do something.

    Prerendering the storefront fetches every brand, its products and its
    reviews across three locales — hundreds of requests from one address in
    half a minute. Before the store pages were prerendered that traffic did not
    exist, and before the limiter was bucketed per route each brand slug had
    its own budget, so neither half was visible alone. Together they failed the
    production image build with a 429 on
    `/catalog/brands/oxide-survival-island`. A carrier NAT or a crawler
    produces the same shape.

    So the global number is deliberately loose, and the endpoints that need a
    real limit carry their own.
    """
    from yupay.core.config import get_settings

    get_settings.cache_clear()
    limit = get_settings().rate_limit_default
    per_minute = int(limit.split("/")[0])
    assert per_minute >= 500, (
        f"{limit} is tight enough to throttle a build or a shared carrier address"
    )
    get_settings.cache_clear()


async def test_order_creation_carries_its_own_budget() -> None:
    """Loosening the coarse net must not loosen the write path with it.

    Order creation had no guard of its own — it relied on the global 120/minute.
    Raising that to 600 without this would have handed one address six hundred
    orders a minute.
    """
    from yupay.core.config import get_settings
    from yupay.modules.auth.ip_guard import bucket_limit

    get_settings.cache_clear()
    settings = get_settings()
    assert bucket_limit(settings, "order-create") < int(
        settings.rate_limit_default.split("/")[0]
    ), "order creation is not tighter than the coarse global net"
    get_settings.cache_clear()
