"""csmarket offers for the item page: cache, budget, breaker, stale twin, id mapping."""

from __future__ import annotations

from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest
from yupay.core.ids import new_id
from yupay.modules.fulfillment.suppliers.csmarket_client import (
    CsmarketError,
    CsmarketUnavailableError,
    Offer,
)
from yupay.modules.skins.listings_csmarket import (
    csmarket_listings_for,
    listing_id_for,
)
from yupay.modules.skins.models import SkinItem

pytestmark = pytest.mark.asyncio


def _offer(offer_id: str, units: int) -> Offer:
    return Offer(
        offer_id=offer_id,
        price_units=units,
        float_value=0.33,
        paint_seed=795,
        stickers=[],
        delivery="instant",
    )


class _Client:
    def __init__(self, *, fail: Exception | None = None, key: bool = True) -> None:
        self.calls: list[str] = []
        self.fail = fail
        self.key = key

    @property
    def configured(self) -> bool:
        return self.key

    async def offers(self, item_id: str, *, timeout: float | None = None) -> list[Offer]:
        self.calls.append(item_id)
        if self.fail:
            raise self.fail
        return [_offer("dear", 13150), _offer("cheap", 11530)]


@pytest.fixture
async def redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


def _item(source_item_id: str | None = "csm-ak") -> SkinItem:
    return SkinItem(
        id=new_id(),
        market_hash_name="AK-47 | Redline (Field-Tested)",
        phase="",
        slug="ak-47-redline-field-tested",
        category="rifles",
        search_text="ak 47 redline field tested",
        cheapest_auto=[],
        source_item_id=source_item_id,
    )


async def _read(
    client: _Client,
    redis: fakeredis.aioredis.FakeRedis,
    item: SkinItem | None = None,
    budget: int = 40,
):  # type: ignore[no-untyped-def]
    return await csmarket_listings_for(
        item or _item(), client=client, redis=redis, budget_per_minute=budget, timeout_seconds=4.0
    )


async def test_listing_id_is_stable_and_js_safe() -> None:
    a = listing_id_for("rBGDFCIOesyZ9-DMdmHEEJA8jPyS5w6vv3S8oZzRvY0")
    assert a == listing_id_for("rBGDFCIOesyZ9-DMdmHEEJA8jPyS5w6vv3S8oZzRvY0")
    assert 0 < a < 2**53
    assert a != listing_id_for("another")


async def test_live_read_sorts_maps_and_caches(redis: fakeredis.aioredis.FakeRedis) -> None:
    client = _Client()
    rows, degraded = await _read(client, redis)
    assert degraded is False
    assert [r.offer_id for r in rows] == ["cheap", "dear"]
    assert rows[0].listing_id == listing_id_for("cheap")
    assert rows[0].price_units == 11530
    assert client.calls == ["csm-ak"]
    again, _ = await _read(client, redis)
    assert len(client.calls) == 1
    assert again[0].offer_id == "cheap"


async def test_an_item_without_a_csmarket_id_is_degraded_and_free(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    client = _Client()
    rows, degraded = await _read(client, redis, _item(None))
    assert (rows, degraded) == ([], True)
    assert client.calls == []


async def test_no_key_never_calls(redis: fakeredis.aioredis.FakeRedis) -> None:
    client = _Client(key=False)
    assert await _read(client, redis) == ([], True)
    assert client.calls == []


async def test_outage_opens_the_breaker_and_serves_stale(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await _read(_Client(), redis)
    await redis.delete("skins:listings:csm:ak-47-redline-field-tested")
    down = _Client(fail=CsmarketUnavailableError("HTTP 502"))
    rows, degraded = await _read(down, redis)
    assert degraded is True
    assert rows[0].offer_id == "cheap"
    assert await redis.exists("skins:csm:breaker")
    await _read(down, redis)
    assert len(down.calls) == 1  # the breaker held the second read off


async def test_item_not_found_is_an_honest_empty_answer(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    gone = _Client(fail=CsmarketError("no", status=404, code="item_not_found"))
    assert await _read(gone, redis) == ([], False)


async def test_spent_budget_falls_back_without_calling(redis: fakeredis.aioredis.FakeRedis) -> None:
    client = _Client()
    rows, degraded = await _read(client, redis, budget=0)
    assert (rows, degraded) == ([], True)
    assert client.calls == []
