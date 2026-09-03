"""Unit tests for ``yupay.modules.gifts.service``.

Covers the pure pricing math (``sell_price_usd`` / ``zone_price_usd``), the
shared ``_cached_json`` fresh/miss/stale/error-with-no-stale cache helper
(fake Redis, no real network), and ``hot_offers``'s filter-then-sort. No
upstream HTTP is exercised here — the G-Engine client itself is covered by
``tests/contract/test_gengine_client.py``; this module stubs ``_client()``
directly. Route-level behaviour (margin, zones, FX) is covered by
``tests/integration/test_gifts_catalog_routes.py``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import fakeredis.aioredis
import pytest
from yupay.core.errors import UpstreamUnavailableError
from yupay.modules.fulfillment.suppliers.gengine_client import GEngineUnavailableError
from yupay.modules.gifts.service import (
    _cached_json,
    hot_offers,
    sell_price_usd,
    zone_price_usd,
)


@pytest.fixture
async def redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


# ---------- sell_price_usd ----------


def test_sell_price_usd_applies_margin_and_rounds_half_up() -> None:
    # 0.97 * 1.10 = 1.067 -> HALF_UP to 2dp = 1.07
    assert sell_price_usd(Decimal("0.97"), Decimal("10")) == Decimal("1.07")


def test_sell_price_usd_zero_margin_is_a_passthrough() -> None:
    assert sell_price_usd(Decimal("5.00"), Decimal("0")) == Decimal("5.00")


# ---------- zone_price_usd ----------


def test_zone_price_usd_finds_the_matching_zone() -> None:
    package = {
        "prices": [
            {"region": "Russia", "currency": "RUB", "price": 99.0, "zone": "RU"},
            {"region": "CIS", "currency": "USD", "price": 1.02, "zone": "CIS"},
        ]
    }
    assert zone_price_usd(package, "CIS") == Decimal("1.02")


def test_zone_price_usd_returns_none_for_a_null_price() -> None:
    package = {"prices": [{"region": "CIS", "currency": "USD", "price": None, "zone": "CIS"}]}
    assert zone_price_usd(package, "CIS") is None


def test_zone_price_usd_returns_none_when_zone_is_absent() -> None:
    package = {"prices": [{"region": "Russia", "currency": "RUB", "price": 99.0, "zone": "RU"}]}
    assert zone_price_usd(package, "CIS") is None


def test_zone_price_usd_handles_no_prices_key() -> None:
    assert zone_price_usd({}, "CIS") is None


# ---------- _cached_json ----------


async def test_cached_json_fresh_hit_never_calls_fetch(
    monkeypatch: pytest.MonkeyPatch, redis: fakeredis.aioredis.FakeRedis
) -> None:
    monkeypatch.setattr("yupay.modules.gifts.service.get_redis", lambda: redis)
    await redis.set("gifts:t1", json.dumps({"a": 1}))

    async def _boom() -> Any:
        raise AssertionError("fetch must not run on a fresh cache hit")

    assert await _cached_json("gifts:t1", 60, _boom) == {"a": 1}


async def test_cached_json_miss_then_store_writes_fresh_and_stale(
    monkeypatch: pytest.MonkeyPatch, redis: fakeredis.aioredis.FakeRedis
) -> None:
    monkeypatch.setattr("yupay.modules.gifts.service.get_redis", lambda: redis)
    calls = 0

    async def _fetch() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"a": 2}

    result = await _cached_json("gifts:t2", 60, _fetch)

    assert result == {"a": 2}
    assert calls == 1
    assert json.loads(await redis.get("gifts:t2")) == {"a": 2}
    assert json.loads(await redis.get("gifts:t2:stale")) == {"a": 2}


async def test_cached_json_serves_stale_on_upstream_error(
    monkeypatch: pytest.MonkeyPatch, redis: fakeredis.aioredis.FakeRedis
) -> None:
    monkeypatch.setattr("yupay.modules.gifts.service.get_redis", lambda: redis)
    await redis.set("gifts:t3:stale", json.dumps({"a": "stale-value"}))

    async def _fetch() -> Any:
        raise GEngineUnavailableError("upstream is down")

    assert await _cached_json("gifts:t3", 60, _fetch) == {"a": "stale-value"}


async def test_cached_json_raises_upstream_unavailable_when_no_stale_exists(
    monkeypatch: pytest.MonkeyPatch, redis: fakeredis.aioredis.FakeRedis
) -> None:
    monkeypatch.setattr("yupay.modules.gifts.service.get_redis", lambda: redis)

    async def _fetch() -> Any:
        raise GEngineUnavailableError("upstream is down")

    with pytest.raises(UpstreamUnavailableError):
        await _cached_json("gifts:t4", 60, _fetch)


# ---------- hot_offers ----------


class _StubGEngineClient:
    """Stands in for ``GEngineClient``: one page of items, then empty."""

    def __init__(self, pages: list[tuple[list[dict[str, Any]], int]]) -> None:
        self._pages = pages
        self.calls = 0

    async def list_gift_apps(
        self, *, limit: int, offset: int, search: str | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        self.calls += 1
        index = offset // limit
        if index >= len(self._pages):
            return [], self._pages[-1][1] if self._pages else 0
        return self._pages[index]


async def test_hot_offers_keeps_only_discounted_items_sorted_descending(
    monkeypatch: pytest.MonkeyPatch, redis: fakeredis.aioredis.FakeRedis
) -> None:
    monkeypatch.setattr("yupay.modules.gifts.service.get_redis", lambda: redis)
    items = [
        {"id": 1, "name": "A", "discount_percent": 10},
        {"id": 2, "name": "B", "discount_percent": 0},
        {"id": 3, "name": "C", "discount_percent": 50},
        {"id": 4, "name": "D", "discount_percent": None},
        {"id": 5, "name": "E", "discount_percent": 25},
    ]
    stub = _StubGEngineClient([(items, len(items))])
    monkeypatch.setattr("yupay.modules.gifts.service._client", lambda: stub)

    offers = await hot_offers()

    assert [o["id"] for o in offers] == [3, 5, 1]
    # A single page covered the whole (short) total, so the scan stopped early.
    assert stub.calls == 1


async def test_hot_offers_caps_at_twelve(
    monkeypatch: pytest.MonkeyPatch, redis: fakeredis.aioredis.FakeRedis
) -> None:
    monkeypatch.setattr("yupay.modules.gifts.service.get_redis", lambda: redis)
    items = [{"id": i, "name": str(i), "discount_percent": i} for i in range(1, 21)]
    stub = _StubGEngineClient([(items, len(items))])
    monkeypatch.setattr("yupay.modules.gifts.service._client", lambda: stub)

    offers = await hot_offers()

    assert len(offers) == 12
    assert [o["id"] for o in offers] == list(range(20, 8, -1))
