"""What the cache-backed price lookups say when they cannot answer.

The happy paths run against a real database next door
(``tests/integration/test_cost_from_voucher_denominations.py``), where the
four-column cache key is the thing worth testing for real. Here is the other
half: every way of coming back empty, and the sentence an operator reads when
it happens.

That sentence is the feature. These lookups read a cache, so "no price" almost
always means "the catalogue was never synced" — a button the operator has —
rather than anything wrong with the supplier. A refusal that said only
"поставщик не вернул цену" would send them to the wrong place.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from yupay.modules.integrations.cost_lookup import _gengine_raw_price, _nova_giftcard_price
from yupay.modules.integrations.models import SkuSupplierMapping

pytestmark = pytest.mark.asyncio


class _Row:
    def __init__(self, price: Decimal | None) -> None:
        self.price_usdt = price


class _Session:
    """Answers one cache lookup with whatever the test put in it."""

    def __init__(self, row: Any) -> None:
        self._row = row

    async def execute(self, _stmt: Any) -> Any:
        row = self._row

        class _Result:
            def scalar_one_or_none(self) -> Any:
                return row

        return _Result()


def _mapping(*, kind: str, product: str, variant: str | None) -> SkuSupplierMapping:
    return SkuSupplierMapping(
        sku_id="sku-1",
        supplier_slug="gengine",
        kind=kind,
        external_product_id=product,
        external_variant_id=variant,
        quantity=1,
        extra={},
        is_active=True,
    )


async def test_gengine_without_a_denomination_cannot_be_priced() -> None:
    """Telegram Stars and the free-amount lines carry their size in
    ``quantity`` and no variant at all — there is no catalogue row to read,
    and a per-unit number would not be this SKU's cost anyway."""
    lookup = await _gengine_raw_price(
        _Session(None), _mapping(kind="game", product="72", variant=None)
    )

    assert lookup.amount is None
    assert "не указан номинал" in (lookup.reason or "")


async def test_gengine_sends_the_operator_to_the_sync_button() -> None:
    lookup = await _gengine_raw_price(
        _Session(None), _mapping(kind="voucher", product="9", variant="727")
    )

    assert lookup.amount is None
    assert "синхронизируйте каталог" in (lookup.reason or "")


async def test_gengine_a_cached_row_without_a_price_is_not_a_price_of_zero() -> None:
    lookup = await _gengine_raw_price(
        _Session(_Row(None)), _mapping(kind="voucher", product="9", variant="727")
    )

    assert lookup.amount is None
    assert "не сообщил цену" in (lookup.reason or "")


async def test_gengine_reads_the_cached_price_and_says_where_it_came_from() -> None:
    lookup = await _gengine_raw_price(
        _Session(_Row(Decimal("22.0932"))), _mapping(kind="voucher", product="9", variant="727")
    )

    assert lookup.reason is None
    assert lookup.amount == Decimal("22.0932")
    # The source string reaches `supplier_price_history.source`, which is how
    # an operator later tells a cached number from a live one.
    assert lookup.source == "supplier_catalog_cache.price_usdt"


async def test_a_nova_gift_card_mapping_with_no_card_is_refused() -> None:
    mapping = _mapping(kind="voucher", product="roblox_global", variant=None)
    mapping.supplier_slug = "nova"

    lookup = await _nova_giftcard_price(_Session(None), mapping)

    assert lookup.amount is None
    assert "card_id" in (lookup.reason or "")


async def test_an_unsynced_nova_category_says_so() -> None:
    mapping = _mapping(kind="voucher", product="roblox_global", variant="50_robux")
    mapping.supplier_slug = "nova"

    lookup = await _nova_giftcard_price(_Session(None), mapping)

    assert "синхронизируйте каталог NOVA" in (lookup.reason or "")


async def test_a_nova_card_row_without_a_price_is_refused_not_zeroed() -> None:
    mapping = _mapping(kind="voucher", product="roblox_global", variant="50_robux")
    mapping.supplier_slug = "nova"

    lookup = await _nova_giftcard_price(_Session(_Row(None)), mapping)

    assert lookup.amount is None
    assert "не сообщила цену" in (lookup.reason or "")
