"""Unit tests for :class:`yupay.modules.fx.service.FxService`.

Providers are stubbed; Redis is faked via ``fakeredis``. No network, no DB.
"""

from __future__ import annotations

from decimal import Decimal

import fakeredis.aioredis
import pytest
from yupay.core.clock import now
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote
from yupay.modules.fx.service import FxService, FxUnavailableError


class StubProvider(FxProvider):
    """Configurable provider for the orchestrator tests."""

    name = "stub"

    def __init__(
        self,
        *,
        rate: Decimal | None = Decimal("90"),
        supported_pairs: set[tuple[str, str]] | None = None,
        fail: bool = False,
        name: str = "stub",
    ) -> None:
        self._rate = rate
        self._pairs = supported_pairs or {("USD", "RUB"), ("USD", "UZS"), ("USD", "USDT")}
        self._fail = fail
        self.name = name
        self.calls = 0

    def supports(self, base: str, quote: str) -> bool:
        return (base.upper(), quote.upper()) in self._pairs

    async def get_rate(self, base: str, quote: str) -> Quote:
        self.calls += 1
        if self._fail or self._rate is None:
            raise FxProviderError("stubbed failure")
        return Quote(
            base=base.upper(),
            quote=quote.upper(),
            rate=self._rate,
            fetched_at=now(),
            source=self.name,
        )


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


async def test_get_rate_cache_miss_calls_provider(redis) -> None:
    provider = StubProvider(rate=Decimal("90"))
    svc = FxService(providers=[provider], redis=redis)
    q = await svc.get_rate("USD", "RUB")
    assert q.rate == Decimal("90")
    assert provider.calls == 1


async def test_get_rate_cache_hit_skips_provider(redis) -> None:
    provider = StubProvider(rate=Decimal("90"))
    svc = FxService(providers=[provider], redis=redis)
    await svc.get_rate("USD", "RUB")  # warms cache
    await svc.get_rate("USD", "RUB")  # second call must hit cache
    assert provider.calls == 1


async def test_chain_falls_through_to_next_provider(redis) -> None:
    failing = StubProvider(fail=True, name="failing")
    good = StubProvider(rate=Decimal("12345.6789"), name="good")
    svc = FxService(providers=[failing, good], redis=redis)
    q = await svc.get_rate("USD", "RUB")
    assert q.rate == Decimal("12345.6789")
    assert q.source == "good"
    assert failing.calls == 1
    assert good.calls == 1


async def test_all_fail_with_stale_returns_stale(redis) -> None:
    good = StubProvider(rate=Decimal("90"), name="primary")
    svc = FxService(providers=[good], redis=redis)
    await svc.get_rate("USD", "RUB")

    # Now flip the provider into failure mode and burn the fresh cache.
    good._fail = True
    await redis.delete("fx:rate:USD:RUB")
    q = await svc.get_rate("USD", "RUB")
    assert q.rate == Decimal("90")  # served from :stale


async def test_all_fail_without_stale_raises(redis) -> None:
    failing = StubProvider(fail=True)
    svc = FxService(providers=[failing], redis=redis)
    with pytest.raises(FxUnavailableError):
        await svc.get_rate("USD", "RUB")


async def test_identity_pair_returns_one(redis) -> None:
    svc = FxService(providers=[StubProvider(fail=True)], redis=redis)
    q = await svc.get_rate("USD", "USD")
    assert q.rate == Decimal(1)


async def test_convert_uses_current_rate(redis) -> None:
    svc = FxService(providers=[StubProvider(rate=Decimal("90"))], redis=redis)
    result = await svc.convert(Decimal("10.50"), base="USD", quote="RUB")
    assert result.amount == Decimal("945.00")
    assert result.rate == Decimal("90")


async def test_unsupported_pair_falls_to_stale_or_raises(redis) -> None:
    only_rub = StubProvider(rate=Decimal("90"), supported_pairs={("USD", "RUB")})
    svc = FxService(providers=[only_rub], redis=redis)
    with pytest.raises(FxUnavailableError):
        await svc.get_rate("USD", "USDT")  # provider doesn't support it
