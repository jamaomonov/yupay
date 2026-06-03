"""Unit tests for GameImportIn validation."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError as PydValidationError
from yupay.modules.integrations.schemas import (
    DenomImportIn,
    GameImportIn,
    NewBrandIn,
    ProductImportIn,
)


def _denom() -> DenomImportIn:
    return DenomImportIn(
        catalogue_name="60 UC",
        denomination="60 UC",
        sku_code="g2b-pubg-60",
        cost_usdt=Decimal("0.85"),
    )


def _product() -> ProductImportIn:
    return ProductImportIn(slug="pubg-uc", name="PUBG UC")


def test_new_brand_requires_new_brand_block() -> None:
    with pytest.raises(PydValidationError):
        GameImportIn(
            game_code="pubg",
            target="new_brand",
            product=_product(),
            margin_percent=Decimal("20"),
            denominations=[_denom()],
        )


def test_existing_brand_requires_brand_id() -> None:
    with pytest.raises(PydValidationError):
        GameImportIn(
            game_code="pubg",
            target="existing_brand",
            product=_product(),
            margin_percent=Decimal("20"),
            denominations=[_denom()],
        )


def test_valid_new_brand_payload() -> None:
    payload = GameImportIn(
        game_code="pubg",
        target="new_brand",
        new_brand=NewBrandIn(slug="pubg-mobile", category_id="cat-1", name="PUBG Mobile"),
        product=_product(),
        margin_percent=Decimal("20"),
        denominations=[_denom()],
    )
    assert payload.new_brand is not None
    assert payload.denominations[0].sku_code == "g2b-pubg-60"


def test_invalid_brand_slug_rejected() -> None:
    with pytest.raises(PydValidationError):
        NewBrandIn(slug="Bad Slug!", category_id="cat-1", name="X")


def test_denominations_must_be_non_empty() -> None:
    with pytest.raises(PydValidationError):
        GameImportIn(
            game_code="pubg",
            target="existing_brand",
            brand_id="b-1",
            product=_product(),
            margin_percent=Decimal("20"),
            denominations=[],
        )
