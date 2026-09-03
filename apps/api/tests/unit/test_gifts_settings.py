"""Unit tests for ``yupay.modules.gifts.settings``.

Covers the CSV zone parsing (``offered_zones`` / ``default_zone``) and the
Redis -> Postgres -> env-default precedence of ``load_margin_percent``. No
real DB: Postgres reads are stubbed with a bare object exposing an async
``get()``. Redis is faked via ``fakeredis`` — mirrors
``tests/unit/test_fx_service.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import fakeredis.aioredis
import pytest
from yupay.core.config import get_settings
from yupay.modules.gifts.settings import default_zone, load_margin_percent, offered_zones


class _NoRowSession:
    """Stand-in for ``AsyncSession``: ``get()`` always misses (no row 1)."""

    async def get(self, model: object, pk: object) -> None:
        return None


class _BoomSession:
    """Stand-in for ``AsyncSession`` that fails the test if consulted."""

    async def get(self, model: object, pk: object) -> None:
        raise AssertionError("DB should not be consulted on a cache hit")


@pytest.fixture
async def redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


def test_offered_zones_parses_uppercases_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    """CSV is split, trimmed, upper-cased, deduped, and keeps first-seen order."""
    monkeypatch.setenv("STEAM_GIFTS_REGIONS", "cis, RU,ru , kz,, UA,uz")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert offered_zones(settings) == ["CIS", "RU", "KZ", "UA", "UZ"]
    finally:
        get_settings.cache_clear()


def test_default_zone_uppercases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STEAM_GIFTS_REGION_DEFAULT", "cis")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert default_zone(settings) == "CIS"
    finally:
        get_settings.cache_clear()


async def test_load_margin_percent_env_default_with_no_row_and_no_cache(
    monkeypatch: pytest.MonkeyPatch, redis: fakeredis.aioredis.FakeRedis
) -> None:
    """No Redis entry, no DB row: falls back to ``settings.steam_gifts_margin_percent``."""
    monkeypatch.setattr("yupay.modules.gifts.settings.get_redis", lambda: redis)

    value = await load_margin_percent(_NoRowSession())  # type: ignore[arg-type]

    assert value == Decimal("10")
    # Write-back: the env default is now cached for the next read.
    cached = await redis.get("gifts:margin")
    assert cached == "10"


async def test_load_margin_percent_cache_hit_skips_db(
    monkeypatch: pytest.MonkeyPatch, redis: fakeredis.aioredis.FakeRedis
) -> None:
    """A warm cache answers without touching Postgres."""
    monkeypatch.setattr("yupay.modules.gifts.settings.get_redis", lambda: redis)
    await redis.set("gifts:margin", "7.5")

    value = await load_margin_percent(_BoomSession())  # type: ignore[arg-type]

    assert value == Decimal("7.5")
