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
