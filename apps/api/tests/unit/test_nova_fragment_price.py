"""The Fragment price lookup, and the one-line convention it got wrong.

`_RawPrice` uses `reason` as the discriminator: set means "no usable number,
ignore everything else", and `refresh_sku_cost_for_mapping` tests it with
`is not None`. Returning `reason=""` on success therefore looked like a
failure with an empty explanation — the refresh took the early return, the
outcome carried a `source` and no `new_cost`, and nothing raised. It shipped
to production and was caught only by reading a number that should not have
been `None`.

So these assert the contract itself, not just the arithmetic.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from yupay.modules.integrations import cost_lookup as cl

pytestmark = pytest.mark.asyncio


class _Client:
    def __init__(self, star: Any = "0.015225", premium: Any = "12.169850") -> None:
        self._star = star
        self._premium = premium
        self.premium_calls: list[dict[str, Any]] = []

    async def fragment_stars_price(self) -> dict[str, Any]:
        return {"price_per_star_usd": self._star}

    async def fragment_premium_quote(self, **kwargs: Any) -> dict[str, Any]:
        self.premium_calls.append(kwargs)
        return {"customer_amount_usd": self._premium}


def _fulfiller(client: _Client) -> Any:
    return SimpleNamespace(_client=lambda: client)


def _mapping(product: str, *, variant: str | None = None, quantity: int = 1) -> Any:
    return SimpleNamespace(
        external_product_id=product, external_variant_id=variant, quantity=quantity
    )


async def test_a_successful_stars_price_reports_no_reason() -> None:
    """`reason=""` is not "no reason" — it is a falsy string the caller reads
    as a refusal, because it tests `is not None`."""
    out = await cl._nova_fragment_price(_fulfiller(_Client()), _mapping("fragment-stars"))

    assert out.reason is None
    assert out.amount == Decimal("0.015225")


async def test_a_successful_premium_price_reports_no_reason() -> None:
    out = await cl._nova_fragment_price(
        _fulfiller(_Client()), _mapping("fragment-premium", variant="3")
    )

    assert out.reason is None
    assert out.amount == Decimal("12.169850")


async def test_a_stars_pack_costs_its_size_times_the_per_star_price() -> None:
    """The mapping's `quantity` is the pack size; the free-amount line carries
    1 and so yields the per-Star cost with no special case."""
    out = await cl._nova_fragment_price(
        _fulfiller(_Client()), _mapping("fragment-stars", quantity=1000)
    )

    assert out.amount == Decimal("15.225000")


async def test_premium_is_quoted_with_a_placeholder_not_a_customer() -> None:
    """The quote ignores the recipient — it priced a username that does not
    exist — so sending a real handle to learn a price that does not depend on
    it would put a customer's data upstream for nothing."""
    client = _Client()

    await cl._nova_fragment_price(_fulfiller(client), _mapping("fragment-premium", variant="12"))

    assert client.premium_calls[0]["username"] == cl._QUOTE_PLACEHOLDER
    assert client.premium_calls[0]["months"] == 12


async def test_a_premium_mapping_without_months_refuses_with_a_reason() -> None:
    out = await cl._nova_fragment_price(
        _fulfiller(_Client()), _mapping("fragment-premium", variant=None)
    )

    assert out.amount is None
    assert out.reason


async def test_a_missing_price_refuses_instead_of_pricing_at_zero() -> None:
    out = await cl._nova_fragment_price(_fulfiller(_Client(star=None)), _mapping("fragment-stars"))

    assert out.amount is None
    assert out.reason
