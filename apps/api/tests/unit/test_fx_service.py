"""Unit tests for :class:`yupay.modules.fx.service.FxService`.

Providers are stubbed; Redis is faked via ``fakeredis``. No network, no DB.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

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


async def test_get_rate_uses_manual_override_over_provider(redis) -> None:
    from yupay.core.clock import now as _now
    from yupay.modules.fx import cache as fx_cache

    provider = StubProvider(rate=Decimal("90"))
    svc = FxService(providers=[provider], redis=redis)
    await fx_cache.write_manual(
        redis,
        quote="UZS",
        use_manual=True,
        manual_rate=Decimal("12500"),
        updated_at=_now(),
    )
    q = await svc.get_rate("USD", "UZS")
    assert q.rate == Decimal("12500")
    assert q.source == "manual"
    assert provider.calls == 0


async def test_get_rate_manual_wins_over_warm_provider_cache(redis) -> None:
    from yupay.core.clock import now as _now
    from yupay.modules.fx import cache as fx_cache

    provider = StubProvider(rate=Decimal("90"))
    svc = FxService(providers=[provider], redis=redis)
    await svc.get_rate("USD", "RUB")
    await fx_cache.write_manual(
        redis,
        quote="RUB",
        use_manual=True,
        manual_rate=Decimal("100"),
        updated_at=_now(),
    )
    q = await svc.get_rate("USD", "RUB")
    assert q.rate == Decimal("100")
    assert q.source == "manual"


async def test_get_rate_uses_provider_when_manual_toggle_off(redis) -> None:
    from yupay.core.clock import now as _now
    from yupay.modules.fx import cache as fx_cache

    provider = StubProvider(rate=Decimal("90"))
    svc = FxService(providers=[provider], redis=redis)
    await fx_cache.write_manual(
        redis,
        quote="RUB",
        use_manual=False,
        manual_rate=Decimal("100"),
        updated_at=_now(),
    )
    q = await svc.get_rate("USD", "RUB")
    assert q.rate == Decimal("90")
    assert q.source == "stub"


async def test_get_market_rate_ignores_manual_override(redis) -> None:
    from yupay.core.clock import now as _now
    from yupay.modules.fx import cache as fx_cache

    provider = StubProvider(rate=Decimal("90"))
    svc = FxService(providers=[provider], redis=redis)
    await fx_cache.write_manual(
        redis,
        quote="RUB",
        use_manual=True,
        manual_rate=Decimal("100"),
        updated_at=_now(),
    )
    q = await svc.get_market_rate("USD", "RUB")
    assert q.rate == Decimal("90")
    assert q.source == "stub"


async def test_convert_uses_manual_rate(redis) -> None:
    from yupay.core.clock import now as _now
    from yupay.modules.fx import cache as fx_cache

    svc = FxService(providers=[StubProvider(rate=Decimal("90"))], redis=redis)
    await fx_cache.write_manual(
        redis,
        quote="RUB",
        use_manual=True,
        manual_rate=Decimal("80"),
        updated_at=_now(),
    )
    result = await svc.convert(Decimal("10"), base="USD", quote="RUB")
    assert result.amount == Decimal("800")
    assert result.source == "manual"


def test_from_row_strips_numeric_scale() -> None:
    from types import SimpleNamespace

    from yupay.modules.fx.quote_settings import _from_row

    row = SimpleNamespace(
        quote="uzs",
        use_manual=True,
        manual_rate=Decimal("12500.0000000000"),
        updated_at=None,
    )
    override = _from_row(row)  # type: ignore[arg-type]
    rate = override.manual_rate
    assert rate is not None
    assert rate == Decimal("12500")
    assert format(rate, "f") == "12500"


@pytest.mark.parametrize(
    "raw",
    ["12500", "13000", "100", "8000.00", "12500.0000000000", "1", "12345.6700"],
)
def test_compact_rate_never_changes_the_number(raw: str) -> None:
    """Only the *scale* may be dropped, never a digit.

    ``rstrip("0")`` on a whole number eats its significant zeros: 12500 became
    125 and priced the whole catalogue at a hundredth. A manual rate bypasses
    the pricing band by design (ADR-0055), so nothing downstream would have
    caught it.
    """
    from yupay.modules.fx.quote_settings import _compact_rate

    compacted = _compact_rate(Decimal(raw))
    assert compacted == Decimal(raw)
    # Plain digits, never scientific notation: this value is serialised into
    # JSON and cached as text.
    assert "E" not in format(compacted, "f").upper()


async def test_failover_alerts_once_then_dedupes(redis, monkeypatch: pytest.MonkeyPatch) -> None:
    alert = AsyncMock(return_value=True)
    monkeypatch.setattr("yupay.modules.fx.failover_alert.send_admin_alert", alert)
    failing = StubProvider(fail=True, name="failing")
    good = StubProvider(rate=Decimal("90"), name="good")
    svc = FxService(providers=[failing, good], redis=redis)

    await svc.get_rate("USD", "RUB")
    alert.assert_awaited_once()
    assert alert.await_args is not None
    assert alert.await_args.kwargs["kind"] == "fx_failover"
    assert "failing → good" in alert.await_args.args[0]

    await redis.delete("fx:rate:USD:RUB")
    await svc.get_rate("USD", "RUB")
    alert.assert_awaited_once()


async def test_second_fallback_pages_again(redis, monkeypatch: pytest.MonkeyPatch) -> None:
    alert = AsyncMock(return_value=True)
    monkeypatch.setattr("yupay.modules.fx.failover_alert.send_admin_alert", alert)
    a = StubProvider(fail=True, name="a")
    b = StubProvider(rate=Decimal("80"), name="b")
    c = StubProvider(rate=Decimal("70"), name="c")
    svc = FxService(providers=[a, b, c], redis=redis)

    q = await svc.get_rate("USD", "RUB")
    assert q.source == "b"
    assert alert.await_count == 1

    b._fail = True
    await redis.delete("fx:rate:USD:RUB")
    q2 = await svc.get_rate("USD", "RUB")
    assert q2.source == "c"
    assert alert.await_count == 2
    assert alert.await_args is not None
    assert "b → c" in alert.await_args.args[0]


async def test_stale_after_all_fail_pages_ops(redis, monkeypatch: pytest.MonkeyPatch) -> None:
    alert = AsyncMock(return_value=True)
    monkeypatch.setattr("yupay.modules.fx.failover_alert.send_admin_alert", alert)
    good = StubProvider(rate=Decimal("90"), name="primary")
    svc = FxService(providers=[good], redis=redis)
    await svc.get_rate("USD", "RUB")
    alert.assert_not_called()

    good._fail = True
    await redis.delete("fx:rate:USD:RUB")
    await svc.get_rate("USD", "RUB")
    alert.assert_awaited_once()
    assert alert.await_args is not None
    assert "stale" in alert.await_args.args[0]


# --- the refresh must not open a window where the cache is empty -------------


class _WatchingProvider(StubProvider):
    """Records what the cache held while the provider was being called."""

    def __init__(self, redis, key: str, **kw) -> None:
        super().__init__(**kw)
        self._redis = redis
        self._key = key
        self.cache_during_call: list[str | None] = []

    async def get_rate(self, base: str, quote: str) -> Quote:
        self.cache_during_call.append(await self._redis.get(self._key))
        return await super().get_rate(base, quote)


async def test_the_refresh_never_empties_the_cache_it_is_refreshing(redis) -> None:
    """`refresh_all` used to DELETE the key and then fetch.

    Between those two steps the cache is empty for the length of a provider
    round trip — up to 1.5s, or ~7.5s if the whole chain has to be walked — and
    every request landing in that window walks the chain itself. The refresh
    runs every five minutes, so that is 288 self-inflicted stampede windows a
    day, on a value that sits on the checkout path: if the chain fails, the
    customer cannot buy.

    Writing over the key instead leaves the old rate readable throughout.
    """
    key = "fx:rate:USD:RUB"
    provider = _WatchingProvider(redis, key, rate=Decimal("90"))
    svc = FxService(providers=[provider], redis=redis)

    await svc.get_rate("USD", "RUB")  # warm the cache
    assert await redis.get(key) is not None

    provider._rate = Decimal("91")
    await svc.refresh_all(AsyncMock(), base="USD", quotes=["RUB"])

    assert provider.cache_during_call[-1] is not None, (
        "the cache was empty while the provider was being called — that is the "
        "stampede window, and every concurrent request falls into it"
    )


async def test_the_refresh_still_bypasses_a_fresh_cache(redis) -> None:
    """The delete existed for a reason: without it the refresh would read its
    own fresh cache entry and never call the provider at all, so `fx_rates`
    history would stop moving."""
    provider = StubProvider(rate=Decimal("90"))
    svc = FxService(providers=[provider], redis=redis)

    await svc.get_rate("USD", "RUB")
    assert provider.calls == 1

    await svc.refresh_all(AsyncMock(), base="USD", quotes=["RUB"])

    assert provider.calls == 2, "the refresh served itself from cache instead of fetching"


async def test_the_refreshed_value_replaces_the_old_one(redis) -> None:
    provider = StubProvider(rate=Decimal("90"))
    svc = FxService(providers=[provider], redis=redis)
    await svc.get_rate("USD", "RUB")

    provider._rate = Decimal("95")
    await svc.refresh_all(AsyncMock(), base="USD", quotes=["RUB"])

    assert (await svc.get_rate("USD", "RUB")).rate == Decimal("95")
