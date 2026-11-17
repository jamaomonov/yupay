"""FazerCards' Telegram cost basis — two reads, no catalogue category."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from yupay.modules.fulfillment.suppliers.fzr_client import FzrError
from yupay.modules.integrations import cost_lookup as cl

pytestmark = pytest.mark.asyncio

# Their live answers, 2026-11-17.
_STARS = {"ok": True, "kind": "telegram_stars", "price_per_star": "0.0152625"}
_PREMIUM = {
    "ok": True,
    "kind": "telegram_premium",
    "plans": [
        {"months": 3, "price_usd": "12.1999"},
        {"months": 6, "price_usd": "16.2699"},
        {"months": 12, "price_usd": "29.4974"},
    ],
}


class _Client:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self._raises = raises

    async def get_telegram_stars(self) -> dict[str, Any]:
        if self._raises:
            raise self._raises
        return _STARS

    async def get_telegram_premium(self) -> dict[str, Any]:
        return _PREMIUM


def _mapping(product: str, *, variant: str | None = None, quantity: int = 1) -> Any:
    return SimpleNamespace(
        external_product_id=product, external_variant_id=variant, quantity=quantity
    )


async def test_a_stars_pack_costs_the_per_star_price_times_its_size() -> None:
    out = await cl._fzr_telegram_price(_Client(), _mapping("fragment-stars", quantity=500))

    assert out.reason is None
    assert out.amount == Decimal("0.0152625") * 500


async def test_the_free_amount_line_costs_one_star() -> None:
    out = await cl._fzr_telegram_price(_Client(), _mapping("fragment-stars"))

    assert out.amount == Decimal("0.0152625")


async def test_premium_reads_the_plan_for_its_months() -> None:
    out = await cl._fzr_telegram_price(_Client(), _mapping("fragment-premium", variant="6"))

    assert out.reason is None
    assert out.amount == Decimal("16.2699")


async def test_a_term_they_do_not_sell_is_a_reason_not_a_zero() -> None:
    out = await cl._fzr_telegram_price(_Client(), _mapping("fragment-premium", variant="24"))

    assert out.amount is None
    assert out.reason


async def test_a_refusal_is_a_reason_not_a_raise() -> None:
    out = await cl._fzr_telegram_price(
        _Client(raises=FzrError("Слишком много запросов", status=429)), _mapping("fragment-stars")
    )

    assert out.amount is None
    assert "Слишком" in (out.reason or "")
