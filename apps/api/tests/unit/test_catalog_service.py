"""Unit tests for :mod:`yupay.modules.catalog.service` price-resolution logic.

Pure-function-shaped: we instantiate ORM objects manually, no DB. Anything that
requires SQL is covered by the integration tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from yupay.modules.catalog.models import Sku, SkuPrice
from yupay.modules.catalog.service import _pick_translation, _resolve_price


class _StubFx:
    """Minimal FxService stand-in. Returns a constant rate."""

    def __init__(self, rate: Decimal) -> None:
        self._rate = rate

    async def convert(self, amount: Decimal, *, base: str, quote: str):
        from yupay.modules.fx.service import ConversionResult

        return ConversionResult(amount=amount * self._rate, rate=self._rate, source="stub")


def _sku(price_usd: str, overrides: dict[str, str] | None = None) -> Sku:
    sku = Sku(
        id="sku-1",
        product_id="p-1",
        sku_code="t",
        denomination="x",
        region=None,
        price_usd=Decimal(price_usd),
        sort_order=0,
        active=True,
    )
    sku.price_overrides = [
        SkuPrice(sku_id="sku-1", currency=cur, price=Decimal(p))
        for cur, p in (overrides or {}).items()
    ]
    return sku


@pytest.mark.asyncio
async def test_resolve_price_returns_none_when_no_currency() -> None:
    assert await _resolve_price(_sku("10"), currency=None, fx=None) is None


@pytest.mark.asyncio
async def test_resolve_price_usd_short_circuits() -> None:
    result = await _resolve_price(_sku("10"), currency="USD", fx=None)
    assert result is not None
    assert result.amount == Decimal("10")
    assert result.source == "usd"


@pytest.mark.asyncio
async def test_resolve_price_prefers_override_over_fx() -> None:
    sku = _sku("10", overrides={"RUB": "950"})
    fx = _StubFx(Decimal("90"))
    result = await _resolve_price(sku, currency="RUB", fx=fx)  # type: ignore[arg-type]
    assert result is not None
    assert result.amount == Decimal("950")
    assert result.source == "override"


@pytest.mark.asyncio
async def test_resolve_price_falls_back_to_fx_when_no_override() -> None:
    fx = _StubFx(Decimal("90"))
    result = await _resolve_price(_sku("10"), currency="RUB", fx=fx)  # type: ignore[arg-type]
    assert result is not None
    assert result.amount == Decimal("900")
    assert result.source == "fx"


@pytest.mark.asyncio
async def test_resolve_price_no_fx_no_override_yields_none() -> None:
    """Caller falls back to ``price_usd`` rather than 503."""
    result = await _resolve_price(_sku("10"), currency="RUB", fx=None)
    assert result is None


def test_pick_translation_uses_requested_locale() -> None:
    class _T:
        def __init__(self, locale: str, name: str) -> None:
            self.locale = locale
            self.name = name
            self.short_description = None
            self.description = None

    translations = [_T("ru", "Игры"), _T("en", "Games"), _T("uz", "Oʻyinlar")]
    name, _, _, _ = _pick_translation(translations, "en")
    assert name == "Games"


def test_pick_translation_falls_back_to_ru() -> None:
    class _T:
        def __init__(self, locale: str, name: str) -> None:
            self.locale = locale
            self.name = name
            self.short_description = None
            self.description = None

    translations = [_T("ru", "Игры")]
    name, _, _, _ = _pick_translation(translations, "en")
    assert name == "Игры"


def test_pick_translation_empty_returns_blank() -> None:
    name, _, _, _ = _pick_translation([], "ru")
    assert name == ""
