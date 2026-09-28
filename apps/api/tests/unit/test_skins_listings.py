"""The listings proxy: fresh cache, budget, breaker, stale twin, snapshot fallback."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import fakeredis.aioredis
import pytest
from yupay.core.ids import new_id
from yupay.modules.fulfillment.suppliers.waxpeer_client import (
    WaxpeerRateLimitedError,
    WaxpeerUnavailableError,
)
from yupay.modules.skins.listings import listings_for
from yupay.modules.skins.models import SkinItem

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skins"
NAME = "AK-47 | Redline (Field-Tested)"


class _Client:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.calls = 0
        self.fail = fail

    async def search_listings(self, names: list[str], *, game: str = "csgo") -> dict[str, Any]:
        self.calls += 1
        if self.fail:
            raise self.fail
        return json.loads((FIXTURES / "search_v2.json").read_text())["items"]  # type: ignore[no-any-return]


@pytest.fixture
async def redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


def _item() -> SkinItem:
    return SkinItem(
        id=new_id(),
        market_hash_name=NAME,
        phase="",
        slug="ak-47-redline-field-tested",
        category="rifles",
        search_text="ak 47 redline field tested",
        cheapest_auto=[{"listing_id": 53857957789, "price_units": 27867}],
    )


async def test_live_read_keeps_auto_only_and_caches(redis: fakeredis.aioredis.FakeRedis) -> None:
    client = _Client()
    listings, degraded = await listings_for(
        _item(), client=client, redis=redis, budget_per_minute=18
    )
    assert degraded is False
    assert [x.listing_id for x in listings] == [53857957789, 53863078495]
    assert listings[0].float_value == pytest.approx(0.3691926896572113)
    assert listings[0].paint_seed == 421
    assert listings[0].inspect_url is not None
    assert listings[0].inspect_url.startswith("steam://rungame/730/")
    assert listings[0].stickers[0]["name"] == "Sticker | The Huns | Budapest 2025"
    again, _ = await listings_for(_item(), client=client, redis=redis, budget_per_minute=18)
    assert client.calls == 1
    assert len(again) == 2


async def test_exhausted_budget_falls_back_to_snapshot(redis: fakeredis.aioredis.FakeRedis) -> None:
    client = _Client()
    listings, degraded = await listings_for(
        _item(), client=client, redis=redis, budget_per_minute=0
    )
    assert (client.calls, degraded) == (0, True)
    assert [(x.listing_id, x.price_units, x.float_value) for x in listings] == [
        (53857957789, 27867, None)
    ]


async def test_429_serves_stale_then_opens_the_breaker(redis: fakeredis.aioredis.FakeRedis) -> None:
    await listings_for(_item(), client=_Client(), redis=redis, budget_per_minute=18)
    await redis.delete("skins:listings:ak-47-redline-field-tested")  # fresh gone, stale kept
    limited = _Client(fail=WaxpeerRateLimitedError("busy", retry_after_ms=1000))
    listings, degraded = await listings_for(
        _item(), client=limited, redis=redis, budget_per_minute=18
    )
    assert (degraded, len(listings), limited.calls) == (True, 2, 1)
    assert await redis.exists("skins:wax:breaker")
    _, degraded = await listings_for(_item(), client=limited, redis=redis, budget_per_minute=18)
    assert limited.calls == 1  # breaker open: not even tried


async def test_outage_without_stale_is_snapshot_fallback(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    down = _Client(fail=WaxpeerUnavailableError("ReadTimeout"))
    listings, degraded = await listings_for(_item(), client=down, redis=redis, budget_per_minute=18)
    assert degraded is True
    assert [x.listing_id for x in listings] == [53857957789]
