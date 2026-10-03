"""Pin ``price_list._row``'s published SKU shape, including ``image_url``.

The catalog endpoint's exact-key assertion lives in the integration suite.
This covers the helper that fills those keys without a database: a missing
``image_url`` keyword would still 200 and only fail once Docker is up.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from yupay.modules.catalog.models import Sku
from yupay.modules.merchants.price_list import _row
from yupay.modules.payments.models import Payment  # noqa: F401

_NOW = datetime(2026, 9, 7, 8, 14, 22, tzinfo=UTC)


def _sku(**overrides: object) -> Sku:
    """Build an ORM SKU with the attributes ``_row`` and ``is_unit_sku`` read."""
    fields: dict[str, object] = {
        "id": "sku-1",
        "product_id": "product-1",
        "sku_code": "pubgm-60",
        "denomination": "60 UC",
        "variable_amount": False,
        "price_usd": Decimal("9.99"),
        "updated_at": _NOW,
        "min_amount_usd": None,
        "max_amount_usd": None,
        "amount_unit": None,
        "min_qty": None,
        "max_qty": None,
    }
    fields.update(overrides)
    return Sku(**fields)


def test_fixed_row_carries_image_url() -> None:
    out = _row(
        _sku(),
        unit=Decimal("1.07"),
        price=Decimal("1.07"),
        image_url="https://cdn.yupay.uz/skus/own.png",
    )
    dumped = out.model_dump()
    assert dumped["kind"] == "fixed"
    assert dumped["image_url"] == "https://cdn.yupay.uz/skus/own.png"
    assert "image_url" in dumped


def test_fixed_row_serialises_missing_artwork_as_null() -> None:
    dumped = _row(_sku(), unit=Decimal("1.07"), price=Decimal("1.07"), image_url=None).model_dump()
    assert dumped["image_url"] is None


def test_unit_and_amount_rows_carry_image_url() -> None:
    unit = _row(
        _sku(amount_unit="stars", min_qty=50, max_qty=5000),
        unit=Decimal("0.016537"),
        price=Decimal("0.02"),
        image_url="https://cdn.yupay.uz/skus/stars.png",
    )
    amount = _row(
        _sku(variable_amount=True, min_amount_usd=Decimal("1"), max_amount_usd=Decimal("500")),
        unit=Decimal("1.07"),
        price=Decimal("1.07"),
        image_url="https://cdn.yupay.uz/products/steam.png",
    )
    assert unit.kind == "unit"
    assert unit.image_url == "https://cdn.yupay.uz/skus/stars.png"
    assert amount.kind == "amount"
    assert amount.image_url == "https://cdn.yupay.uz/products/steam.png"
