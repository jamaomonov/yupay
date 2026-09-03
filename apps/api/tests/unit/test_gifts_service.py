"""Unit tests for ``yupay.modules.gifts.service``.

Covers the pure pricing math (``sell_price_usd`` / ``zone_price_usd`` /
``zone_region_code``) — the latter two share one price-entry finder, so the
billed price and the supplier's wire region code can never come from
different entries — the shared ``_cached_json`` fresh/miss/stale/
error-with-no-stale cache helper (fake Redis, no real network), and
``hot_offers``'s filter-then-sort. No upstream HTTP is exercised here — the
G-Engine client itself is covered by ``tests/contract/test_gengine_client.py``;
this module stubs ``_client()`` directly. Route-level behaviour (margin,
zones, FX) is covered by ``tests/integration/test_gifts_catalog_routes.py``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import fakeredis.aioredis
import pytest
from yupay.core.errors import UpstreamUnavailableError
from yupay.modules.fulfillment.suppliers.gengine_client import (
    GIFT_SEARCH_MAX,
    GEngineUnavailableError,
)
from yupay.modules.gifts.service import (
    _cached_json,
    _search_cache_key,
    countries_for_zone,
    hot_offers,
    sell_price_usd,
    zone_for_country,
    zone_price_usd,
    zone_region_code,
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


# ---------- zone_region_code ----------


def test_zone_region_code_returns_the_code_for_a_priced_zone() -> None:
    package = {
        "prices": [
            {"region": "ru", "currency": "RUB", "price": 99.0, "zone": "RU"},
            {"region": "ge", "currency": "USD", "price": 1.02, "zone": "CIS"},
        ]
    }
    assert zone_region_code(package, "CIS") == "ge"


def test_zone_region_code_returns_none_for_a_null_price() -> None:
    package = {"prices": [{"region": "ge", "currency": "USD", "price": None, "zone": "CIS"}]}
    assert zone_region_code(package, "CIS") is None


def test_zone_region_code_returns_none_when_zone_is_absent() -> None:
    package = {"prices": [{"region": "ru", "currency": "RUB", "price": 99.0, "zone": "RU"}]}
    assert zone_region_code(package, "CIS") is None


def test_zone_region_code_handles_no_prices_key() -> None:
    assert zone_region_code({}, "CIS") is None


def test_zone_region_code_returns_none_for_a_priced_entry_missing_region() -> None:
    """A malformed upstream entry — priced, but with no ``region`` key at
    all — must not raise (``KeyError`` -> 500 on the money path).
    ``zone_price_usd`` still prices this same entry: the two are allowed to
    disagree only in this malformed case, and checkout's own guard is what
    turns the missing code into a clean 4xx rather than a crash."""
    package = {"prices": [{"currency": "USD", "price": 1.02, "zone": "CIS"}]}
    assert zone_region_code(package, "CIS") is None
    assert zone_price_usd(package, "CIS") == Decimal("1.02")


def test_zone_region_code_returns_none_for_a_priced_entry_with_a_blank_region() -> None:
    package = {"prices": [{"region": "", "currency": "USD", "price": 1.02, "zone": "CIS"}]}
    assert zone_region_code(package, "CIS") is None


def test_zone_price_usd_and_zone_region_code_share_the_same_priced_entry() -> None:
    """A package can carry two entries for the same zone — one with a null
    price, one live. Both finders must skip the null-price entry and agree
    on the live one, so the billed price and the wire region code can never
    come from two different entries."""
    package = {
        "prices": [
            {"region": "kz", "currency": "USD", "price": None, "zone": "CIS"},
            {"region": "ge", "currency": "USD", "price": 1.02, "zone": "CIS"},
        ]
    }
    assert zone_price_usd(package, "CIS") == Decimal("1.02")
    assert zone_region_code(package, "CIS") == "ge"


# ---------- zone_for_country / countries_for_zone ----------

_OFFERED = ["CIS", "RU", "KZ", "UA"]


def test_zone_for_country_resolves_a_cis_country() -> None:
    assert zone_for_country("uz", offered=_OFFERED) == "CIS"


def test_zone_for_country_own_zone_wins_over_cis_membership() -> None:
    # KZ has its own zone, distinct from the CIS bucket.
    assert zone_for_country("KZ", offered=_OFFERED) == "KZ"


def test_zone_for_country_returns_none_for_an_unsold_country() -> None:
    assert zone_for_country("DE", offered=_OFFERED) is None


def test_zone_for_country_respects_the_offered_list() -> None:
    # UZ is a CIS country, but CIS isn't offered here.
    assert zone_for_country("UZ", offered=["RU"]) is None


def test_countries_for_zone_puts_uz_first_for_cis() -> None:
    package: dict[str, Any] = {"prices": [{"zone": "CIS", "region": "ge", "price": 1.0}]}
    assert countries_for_zone("CIS", package)[0] == "UZ"


def test_countries_for_zone_falls_back_to_the_package_entrys_own_region() -> None:
    # MENA isn't in the curated map — falls back to this package's own
    # representative country for that zone, upper-cased.
    package: dict[str, Any] = {"prices": [{"zone": "MENA", "region": "tr", "price": 3.5}]}
    assert countries_for_zone("MENA", package) == ("TR",)


def test_countries_for_zone_returns_empty_when_the_zone_is_unmapped_and_unpriced() -> None:
    package: dict[str, Any] = {"prices": []}
    assert countries_for_zone("MENA", package) == ()


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


# ---------- _search_cache_key ----------


def test_search_cache_key_identical_past_gift_search_max() -> None:
    """``GEngineClient.list_gift_apps`` truncates ``search`` to
    ``GIFT_SEARCH_MAX`` before it ever reaches G-Engine (gengine_client.py),
    so two queries that differ only after that point resolve to the exact
    same upstream call and must share one cache key — not mint a distinct
    Redis entry (plus 24h stale twin) per superfluous tail character."""
    head = "dead cells" * 4  # well past GIFT_SEARCH_MAX on its own
    assert len(head) > GIFT_SEARCH_MAX
    key_one = _search_cache_key(f"{head}-tail-one", offset=0, limit=24)
    key_two = _search_cache_key(f"{head}-a-very-different-and-longer-tail", offset=0, limit=24)
    assert key_one == key_two


def test_search_cache_key_differs_within_gift_search_max() -> None:
    """Sanity check on the other side: a real difference inside the first
    ``GIFT_SEARCH_MAX`` characters — the part upstream actually sees — must
    still produce a different key."""
    key_one = _search_cache_key("a" * GIFT_SEARCH_MAX, offset=0, limit=24)
    key_two = _search_cache_key("b" * GIFT_SEARCH_MAX, offset=0, limit=24)
    assert key_one != key_two


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
