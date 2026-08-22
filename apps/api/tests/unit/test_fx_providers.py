"""Unit tests for individual FX provider adapters.

HTTP is mocked via ``respx`` so these run hermetically.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx
from yupay.modules.fx.providers import (
    CoingeckoProvider,
    ExchangerateHostProvider,
    FxProviderError,
    FxRatesApiProvider,
    OpenExchangeRatesProvider,
)

URL_PRIMARY = "https://api.exchangerate.host/latest"
URL_FALLBACK = "https://openexchangerates.org/api/latest.json"
URL_CRYPTO = "https://api.coingecko.com/api/v3/simple/price"
URL_RATES_API = "https://api.fxratesapi.com/latest"


@respx.mock
async def test_exchangerate_host_returns_decimal_rate() -> None:
    respx.get(URL_PRIMARY).mock(return_value=httpx.Response(200, json={"rates": {"RUB": 90.1234}}))
    p = ExchangerateHostProvider(URL_PRIMARY, timeout_seconds=1.0)
    q = await p.get_rate("USD", "RUB")
    assert q.rate == Decimal("90.1234")
    assert q.base == "USD"
    assert q.quote == "RUB"
    assert q.source == "exchangerate.host"


@respx.mock
async def test_exchangerate_host_raises_on_missing_quote() -> None:
    respx.get(URL_PRIMARY).mock(return_value=httpx.Response(200, json={"rates": {}}))
    p = ExchangerateHostProvider(URL_PRIMARY, timeout_seconds=1.0)
    with pytest.raises(FxProviderError):
        await p.get_rate("USD", "RUB")


@respx.mock
async def test_exchangerate_host_raises_on_5xx() -> None:
    respx.get(URL_PRIMARY).mock(return_value=httpx.Response(503, json={}))
    p = ExchangerateHostProvider(URL_PRIMARY, timeout_seconds=1.0)
    with pytest.raises(FxProviderError):
        await p.get_rate("USD", "RUB")


def test_openexchangerates_skips_without_key() -> None:
    p = OpenExchangeRatesProvider(URL_FALLBACK, api_key="", timeout_seconds=1.0)
    assert p.supports("USD", "RUB") is False


@respx.mock
async def test_openexchangerates_uses_key_and_returns_rate() -> None:
    respx.get(URL_FALLBACK).mock(return_value=httpx.Response(200, json={"rates": {"RUB": 91.5}}))
    p = OpenExchangeRatesProvider(URL_FALLBACK, api_key="abc", timeout_seconds=1.0)
    q = await p.get_rate("USD", "RUB")
    assert q.rate == Decimal("91.5")
    assert q.source == "openexchangerates"


@respx.mock
async def test_coingecko_inverts_usd_per_coin() -> None:
    respx.get(URL_CRYPTO).mock(return_value=httpx.Response(200, json={"tether": {"usd": 1.0002}}))
    p = CoingeckoProvider(URL_CRYPTO, timeout_seconds=1.0)
    q = await p.get_rate("USD", "USDT")
    # 1 USD ≈ 1/1.0002 USDT = 0.9998000400...
    assert q.rate == Decimal("0.9998000400")
    assert q.source == "coingecko"


def test_coingecko_only_supports_known_coins() -> None:
    p = CoingeckoProvider(URL_CRYPTO, timeout_seconds=1.0)
    assert p.supports("USD", "USDT") is True
    assert p.supports("USD", "RUB") is False
    assert p.supports("RUB", "USDT") is False


def test_fxratesapi_skips_without_key() -> None:
    p = FxRatesApiProvider(URL_RATES_API, api_key="", timeout_seconds=1.0)
    assert p.supports("USD", "UZS") is False


@respx.mock
async def test_fxratesapi_returns_decimal_rate() -> None:
    respx.get(URL_RATES_API).mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "base": "USD", "rates": {"UZS": 11853.552324064}},
        )
    )
    p = FxRatesApiProvider(URL_RATES_API, api_key="fxr_test", timeout_seconds=1.0)
    q = await p.get_rate("USD", "UZS")
    assert q.rate == Decimal("11853.552324064")
    assert q.source == "fxratesapi.com"


@respx.mock
async def test_fxratesapi_raises_when_success_false() -> None:
    respx.get(URL_RATES_API).mock(
        return_value=httpx.Response(200, json={"success": False, "base": "USD", "rates": {}})
    )
    p = FxRatesApiProvider(URL_RATES_API, api_key="fxr_test", timeout_seconds=1.0)
    with pytest.raises(FxProviderError):
        await p.get_rate("USD", "UZS")
