"""Integration test for ``GET /api/v1/fx/rates``.

We patch ``build_default_service`` to return an :class:`FxService` wired to a fake
Redis and a stub provider chain. No outbound HTTP, no real Redis.
"""

from __future__ import annotations

from decimal import Decimal

import fakeredis.aioredis
import pytest
from httpx import AsyncClient
from yupay.core.clock import now
from yupay.modules.fx.providers.base import FxProvider, Quote
from yupay.modules.fx.service import FxService

pytestmark = pytest.mark.asyncio


class _StubProvider(FxProvider):
    name = "stub"

    def __init__(self, rates: dict[str, Decimal]) -> None:
        self._rates = rates

    def supports(self, base: str, quote: str) -> bool:
        return base.upper() == "USD" and quote.upper() in self._rates

    async def get_rate(self, base: str, quote: str) -> Quote:
        return Quote(
            base=base.upper(),
            quote=quote.upper(),
            rate=self._rates[quote.upper()],
            fetched_at=now(),
            source=self.name,
        )


@pytest.fixture
def _stub_service(monkeypatch):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    provider = _StubProvider(
        {"RUB": Decimal("90.5"), "UZS": Decimal("12700.25"), "USDT": Decimal("1.0001")}
    )

    def _build_default_service(*, settings=None, redis=redis, _provider=provider):
        return FxService(providers=[_provider], redis=redis)

    monkeypatch.setattr("yupay.modules.fx.routes.build_default_service", _build_default_service)


async def test_get_rates_returns_supported_pairs(
    integration_client: AsyncClient, _stub_service: None
) -> None:
    r = await integration_client.get("/api/v1/fx/rates")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base"] == "USD"
    quotes = {rate["quote"]: rate for rate in body["rates"]}
    assert quotes["RUB"]["rate"] == "90.5"
    assert quotes["UZS"]["rate"] == "12700.25"
    assert quotes["USDT"]["rate"] == "1.0001"
    assert all(r["source"] == "stub" for r in body["rates"])


async def test_get_rates_503_when_chain_completely_fails(
    integration_client: AsyncClient, monkeypatch
) -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    class _Always(_StubProvider):
        async def get_rate(self, base: str, quote: str) -> Quote:
            from yupay.modules.fx.providers.base import FxProviderError

            raise FxProviderError("dead")

    provider = _Always({"RUB": Decimal("0"), "UZS": Decimal("0"), "USDT": Decimal("0")})
    monkeypatch.setattr(
        "yupay.modules.fx.routes.build_default_service",
        lambda *_args, **_kw: FxService(providers=[provider], redis=redis),
    )

    r = await integration_client.get("/api/v1/fx/rates")
    assert r.status_code == 503
