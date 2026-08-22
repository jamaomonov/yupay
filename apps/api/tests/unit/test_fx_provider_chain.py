"""Admin-ordered FX provider chain."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest
from yupay.core.clock import now
from yupay.core.errors import ValidationError
from yupay.modules.fx.probe import probe_chain
from yupay.modules.fx.provider_chain import (
    DEFAULT_SLUGS,
    ChainItem,
    save_chain,
    write_chain_cache,
)
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote
from yupay.modules.fx.service import FxService


class StubProvider(FxProvider):
    name = "stub"
    slug = "stub"

    def __init__(self, *, rate: Decimal = Decimal("90"), slug: str = "stub") -> None:
        self._rate = rate
        self.slug = slug
        self.name = slug

    def supports(self, base: str, quote: str) -> bool:
        return base.upper() == "USD"

    async def get_rate(self, base: str, quote: str) -> Quote:
        return Quote(
            base=base.upper(),
            quote=quote.upper(),
            rate=self._rate,
            fetched_at=now(),
            source=self.name,
        )


@pytest.fixture
async def redis() -> object:
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest.mark.asyncio
async def test_save_chain_rejects_partial_catalog() -> None:
    with pytest.raises(ValidationError):
        await save_chain(
            AsyncMock(),
            items=[ChainItem(slug="fxratesapi", enabled=True, sort_order=0)],
        )


@pytest.mark.asyncio
async def test_redis_chain_reorders_constructor_list(redis: object) -> None:
    primary = StubProvider(rate=Decimal("111"), slug="fxratesapi")
    other = StubProvider(rate=Decimal("222"), slug="exchangerate-host")
    svc = FxService(providers=[other, primary], redis=redis)  # type: ignore[arg-type]
    items = [
        ChainItem(slug=slug, enabled=True, sort_order=i) for i, slug in enumerate(DEFAULT_SLUGS)
    ]
    await write_chain_cache(redis, items)  # type: ignore[arg-type]
    q = await svc.get_rate("USD", "RUB")
    assert q.rate == Decimal("111")
    assert q.source == "fxratesapi"


@pytest.mark.asyncio
async def test_probe_marks_primary_and_captures_errors() -> None:
    class _P(StubProvider):
        def supports(self, base: str, quote: str) -> bool:
            return quote == "UZS"

        async def get_rate(self, base: str, quote: str) -> Quote:
            if quote == "UZS":
                return await super().get_rate(base, quote)
            raise FxProviderError("nope")

    chain = [
        ChainItem(slug=slug, enabled=True, sort_order=i) for i, slug in enumerate(DEFAULT_SLUGS)
    ]
    out = await probe_chain(
        [
            _P(rate=Decimal("11853"), slug="fxratesapi"),
            StubProvider(rate=Decimal("12700"), slug="exchangerate-host"),
        ],
        chain,
        ["UZS", "RUB"],
    )
    fxr = next(i for i in out.items if i.slug == "fxratesapi")
    assert fxr.role == "primary"
    uzs = next(q for q in fxr.quotes if q.quote == "UZS")
    assert uzs.rate == Decimal("11853")
    rub = next(q for q in fxr.quotes if q.quote == "RUB")
    assert rub.error == "не обслуживает эту пару"
