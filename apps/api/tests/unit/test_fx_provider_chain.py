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
    provider_slug,
    save_chain,
    write_chain_cache,
)
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote
from yupay.modules.fx.service import FxService, FxUnavailableError


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


@pytest.mark.asyncio
async def test_a_disabled_provider_is_not_queried(redis: object) -> None:
    """Unticking "В цепочке" must mean it, not "ask it last".

    `_ordered_providers` skipped a disabled item before recording its slug as
    seen, and the trailing "append whatever the chain did not mention" loop
    then put it straight back at the end. An operator who switched off a
    source for returning bad data still had it answering as the last fallback.
    """
    disabled = StubProvider(rate=Decimal("111"), slug="fxratesapi")
    kept = StubProvider(rate=Decimal("222"), slug="exchangerate-host")
    svc = FxService(providers=[disabled, kept], redis=redis)  # type: ignore[arg-type]
    await write_chain_cache(
        redis,  # type: ignore[arg-type]
        [
            ChainItem(slug="fxratesapi", enabled=False, sort_order=0),
            ChainItem(slug="exchangerate-host", enabled=True, sort_order=1),
        ],
    )

    ordered = await svc._ordered_providers()
    assert [provider_slug(p) for p in ordered] == ["exchangerate-host"]


@pytest.mark.asyncio
async def test_a_disabled_primary_does_not_answer_even_when_the_rest_fail(
    redis: object,
) -> None:
    """The point of switching a source off is that its number never ships."""

    class _Failing(StubProvider):
        async def get_rate(self, base: str, quote: str) -> Quote:
            raise FxProviderError("upstream down")

    disabled = StubProvider(rate=Decimal("111"), slug="fxratesapi")
    failing = _Failing(slug="exchangerate-host")
    svc = FxService(providers=[disabled, failing], redis=redis)  # type: ignore[arg-type]
    await write_chain_cache(
        redis,  # type: ignore[arg-type]
        [
            ChainItem(slug="fxratesapi", enabled=False, sort_order=0),
            ChainItem(slug="exchangerate-host", enabled=True, sort_order=1),
        ],
    )

    with pytest.raises(FxUnavailableError):
        await svc.get_rate("USD", "RUB", allow_stale=False)


@pytest.mark.asyncio
async def test_a_chain_may_not_leave_a_quote_uncovered() -> None:
    """Now that "off" means off, one unticked box can take a currency off sale.

    Only CoinGecko answers USD→USDT; the fiat adapters reject it. Disabling it
    used to be harmless because the ordering code swept disabled slugs back in
    as a last resort. Nothing breaks at save time either — the fresh cache
    still answers — and then the stale entry expires and checkout 503s.
    """
    from yupay.modules.fx.provider_chain import assert_chain_covers_quotes

    class _Fiat(StubProvider):
        def supports(self, base: str, quote: str) -> bool:
            return quote.upper() in {"UZS", "RUB"}

    class _Crypto(StubProvider):
        def supports(self, base: str, quote: str) -> bool:
            return quote.upper() == "USDT"

    providers = [_Fiat(slug="exchangerate-host"), _Crypto(slug="coingecko")]
    quotes = ["UZS", "RUB", "USDT"]

    assert_chain_covers_quotes(
        [
            ChainItem(slug="exchangerate-host", enabled=True, sort_order=0),
            ChainItem(slug="coingecko", enabled=True, sort_order=1),
        ],
        providers=providers,
        quotes=quotes,
    )

    with pytest.raises(ValidationError) as caught:
        assert_chain_covers_quotes(
            [
                ChainItem(slug="exchangerate-host", enabled=True, sort_order=0),
                ChainItem(slug="coingecko", enabled=False, sort_order=1),
            ],
            providers=providers,
            quotes=quotes,
        )
    # `AppError(detail, **extra)` nests the kwarg, so the payload the client
    # sees as `extra` lives at `.extra["extra"]` — house convention, see
    # `core.errors`.
    assert caught.value.extra["extra"]["uncovered"] == ["USDT"]
