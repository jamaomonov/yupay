"""Supplier stock semantics for voucher SKUs.

The whole feature turns on one convention — NULL means "not tracked", zero means
"do not sell" — and on reading G2B's ``-1`` as the former rather than the latter.
Getting that backwards would quietly pull every unlimited line off the
storefront, so it is pinned here rather than left to the reader.
"""

from __future__ import annotations

from decimal import Decimal

from yupay.modules.catalog.models import Sku
from yupay.modules.integrations.stock_refresh import normalise_stock


def _sku(stock: int | None) -> Sku:
    return Sku(
        id="s1",
        product_id="p1",
        sku_code="c1",
        price_usd=Decimal("1"),
        supplier_stock=stock,
    )


class TestNormaliseStock:
    def test_a_count_is_kept(self) -> None:
        assert normalise_stock(423) == 423
        assert normalise_stock(0) == 0

    def test_minus_one_means_untracked_not_empty(self) -> None:
        # G2B answers -1 on lines that are demonstrably sellable. Reading it as
        # a deficit would hide them; NULL is the honest "nothing was claimed".
        assert normalise_stock(-1) is None
        assert normalise_stock(-99) is None

    def test_silence_claims_nothing(self) -> None:
        assert normalise_stock(None) is None
        assert normalise_stock("many") is None
        assert normalise_stock({}) is None

    def test_booleans_are_not_counts(self) -> None:
        # bool is an int in Python; True would otherwise read as "1 left".
        # Bound to names because ruff rejects a bare boolean argument (FBT003),
        # and the point here is precisely that a bool reaches the function.
        yes, no = True, False
        assert normalise_stock(yes) is None
        assert normalise_stock(no) is None

    def test_floats_are_truncated_to_a_count(self) -> None:
        assert normalise_stock(3.0) == 3


class TestSkuInStock:
    def test_untracked_is_sellable(self) -> None:
        # Every game top-up carries NULL and must stay buyable.
        assert _sku(None).in_stock is True

    def test_zero_is_not_sellable(self) -> None:
        assert _sku(0).in_stock is False

    def test_a_positive_count_is_sellable(self) -> None:
        assert _sku(1).in_stock is True
        assert _sku(422).in_stock is True

    def test_stock_is_independent_of_active(self) -> None:
        # An operator switching a SKU off and a supplier running dry are
        # different facts; `in_stock` reports only the second one, so the
        # operator's intent survives the next refresh.
        sku = _sku(5)
        sku.active = False
        assert sku.in_stock is True
