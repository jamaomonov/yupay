"""Trade link parsing and the advisory check (plan 3a, Task 2)."""

from __future__ import annotations

import fakeredis
import pytest
from yupay.core.errors import ValidationError
from yupay.modules.skins.tradelink import check_tradelink, parse_tradelink

LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1039652352&token=LBCWEQ8s"


def test_a_steam_trade_link_parses_to_the_account() -> None:
    link = parse_tradelink(f"  {LINK}  ")
    assert (link.partner, link.token) == (1039652352, "LBCWEQ8s")
    assert link.steam_id == 76561198999918080
    assert link.url == LINK


@pytest.mark.parametrize(
    "raw",
    [
        "https://steamcommunity.com/tradeoffer/new/?partner=abc&token=LBCWEQ8s",
        "https://evil.example/tradeoffer/new/?partner=1&token=LBCWEQ8s",
        "http://steamcommunity.com/tradeoffer/new/?partner=1&token=LBCWEQ8s",
        "https://steamcommunity.com/tradeoffer/new/?partner=1",
        "",
    ],
)
def test_anything_else_is_refused(raw: str) -> None:
    with pytest.raises(ValidationError):
        parse_tradelink(raw)


class _Wax:
    def __init__(self, info: str | None = None, fail: bool = False) -> None:
        self.info, self.fail, self.calls = info, fail, 0

    async def check_tradelink(self, url: str) -> str | None:
        self.calls += 1
        if self.fail:
            raise ConnectionError("down")
        return self.info


class _Steam:
    def __init__(self, days: int | None = 0, fail: bool = False) -> None:
        self.days, self.fail = days, fail

    async def trade_hold_days(self, steam_id: int, token: str) -> int | None:
        if self.fail:
            raise ConnectionError("down")
        return self.days


def _redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_a_clean_link_is_ok_and_cached() -> None:
    wax, redis = _Wax(), _redis()
    first = await check_tradelink(LINK, waxpeer=wax, steam=_Steam(), redis=redis)
    second = await check_tradelink(LINK, waxpeer=wax, steam=_Steam(), redis=redis)
    assert (first.ok, first.reason) == (True, None)
    assert second == first
    assert wax.calls == 1


@pytest.mark.parametrize(
    ("info", "days", "reason"),
    [
        ("This profile is private", 0, "private"),
        ("Please set your steam inventory public", 0, "private"),
        ("Public API key is not set", 0, "invalid"),
        ("User has a trade ban", 0, "trade_ban"),
        (None, 15, "hold"),
    ],
)
@pytest.mark.asyncio
async def test_a_problem_is_named(info: str | None, days: int, reason: str) -> None:
    v = await check_tradelink(LINK, waxpeer=_Wax(info), steam=_Steam(days), redis=_redis())
    assert (v.ok, v.reason) == (False, reason)


@pytest.mark.asyncio
async def test_an_outage_never_blocks_and_is_not_cached() -> None:
    wax, redis = _Wax(fail=True), _redis()
    v = await check_tradelink(LINK, waxpeer=wax, steam=_Steam(), redis=redis)
    assert (v.ok, v.reason) == (True, "unavailable")
    await redis.delete("skins:tradelink:breaker")  # past the breaker window
    await check_tradelink(LINK, waxpeer=wax, steam=_Steam(), redis=redis)
    assert wax.calls == 2


@pytest.mark.asyncio
async def test_the_token_never_reaches_a_redis_key() -> None:
    redis = _redis()
    await check_tradelink(LINK, waxpeer=_Wax(), steam=_Steam(), redis=redis)
    keys = [k async for k in redis.scan_iter("*")]
    assert keys
    assert not any("LBCWEQ8s" in k for k in keys)


@pytest.mark.asyncio
async def test_an_outage_opens_a_breaker_that_skips_the_upstream() -> None:
    redis = _redis()
    down = _Wax(fail=True)
    await check_tradelink(LINK, waxpeer=down, steam=_Steam(), redis=redis)
    healthy = _Wax()
    v = await check_tradelink(LINK, waxpeer=healthy, steam=_Steam(), redis=redis)
    assert (v.ok, v.reason) == (True, "unavailable")
    assert healthy.calls == 0
