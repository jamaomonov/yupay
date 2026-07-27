"""Unit tests for admin catalog schema validation.

Pure Pydantic — no DB, no HTTP. Covers the ``ck_skus_variable_amount_complete``
DB CHECK mirrored in :mod:`yupay.modules.catalog.admin_schemas`, so an admin
gets a readable 422 instead of an opaque ``IntegrityError`` when they submit an
incomplete variable-amount SKU. The end-to-end round trip through the actual
HTTP endpoints is covered in
``tests/integration/test_admin_catalog_routes.py``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError
from yupay.modules.catalog.admin_schemas import (
    BrandCreate,
    BrandUpdate,
    ProductCreate,
    ProductUpdate,
    SkuCreate,
    SkuUpdate,
)

_BASE_CREATE: dict[str, object] = {
    "product_id": "prod-1",
    "sku_code": "steam-wallet-topup",
    "price_usd": "1",
}


# ---------- SkuCreate ----------


def test_sku_create_variable_amount_false_ignores_missing_bounds() -> None:
    """Default (non-variable) SKUs don't need min/max/multiplier at all."""
    sku = SkuCreate(**_BASE_CREATE)  # type: ignore[arg-type]
    assert sku.variable_amount is False
    assert sku.min_amount_usd is None
    assert sku.max_amount_usd is None
    assert sku.rate_multiplier is None


def test_sku_create_variable_amount_true_requires_all_three_fields() -> None:
    with pytest.raises(ValidationError, match="variable_amount SKUs require"):
        SkuCreate(**_BASE_CREATE, variable_amount=True)  # type: ignore[arg-type]


def test_sku_create_variable_amount_true_partial_fields_still_rejected() -> None:
    """Only some of the three set — still incomplete, still 422."""
    with pytest.raises(ValidationError, match="max_amount_usd"):
        SkuCreate(
            **_BASE_CREATE,  # type: ignore[arg-type]
            variable_amount=True,
            min_amount_usd=Decimal("1"),
            rate_multiplier=Decimal("1.08"),
        )


def test_sku_create_variable_amount_true_max_below_min_rejected() -> None:
    with pytest.raises(ValidationError, match="max_amount_usd must be >= min_amount_usd"):
        SkuCreate(
            **_BASE_CREATE,  # type: ignore[arg-type]
            variable_amount=True,
            min_amount_usd=Decimal("50"),
            max_amount_usd=Decimal("10"),
            rate_multiplier=Decimal("1.08"),
        )


def test_sku_create_variable_amount_true_complete_round_trip() -> None:
    """A fully-specified variable SKU passes validation and keeps its values."""
    sku = SkuCreate(
        **_BASE_CREATE,  # type: ignore[arg-type]
        variable_amount=True,
        min_amount_usd=Decimal("1"),
        max_amount_usd=Decimal("500"),
        rate_multiplier=Decimal("1.08"),
    )
    assert sku.variable_amount is True
    assert sku.min_amount_usd == Decimal("1")
    assert sku.max_amount_usd == Decimal("500")
    assert sku.rate_multiplier == Decimal("1.08")


def test_sku_create_rejects_non_positive_min_and_multiplier() -> None:
    # Field(gt=0) on min_amount_usd / rate_multiplier fires before the
    # cross-field check even gets a chance to run.
    with pytest.raises(ValidationError):
        SkuCreate(
            **_BASE_CREATE,  # type: ignore[arg-type]
            variable_amount=True,
            min_amount_usd=Decimal("0"),
            max_amount_usd=Decimal("500"),
            rate_multiplier=Decimal("1.08"),
        )


# ---------- SkuUpdate ----------


def test_sku_update_variable_amount_omitted_skips_validation() -> None:
    """A PATCH that doesn't touch variable_amount at all is never rejected
    for missing bounds — it's not claiming to be a variable SKU."""
    patch = SkuUpdate(sku_code="new-code")
    assert patch.variable_amount is None


def test_sku_update_variable_amount_true_requires_all_three_fields() -> None:
    with pytest.raises(ValidationError, match="variable_amount SKUs require"):
        SkuUpdate(variable_amount=True)


def test_sku_update_variable_amount_true_complete_round_trip() -> None:
    patch = SkuUpdate(
        variable_amount=True,
        min_amount_usd=Decimal("1"),
        max_amount_usd=Decimal("500"),
        rate_multiplier=Decimal("1.08"),
    )
    assert patch.min_amount_usd == Decimal("1")
    assert patch.max_amount_usd == Decimal("500")
    assert patch.rate_multiplier == Decimal("1.08")


def test_sku_update_variable_amount_false_with_null_bounds_is_valid() -> None:
    """Turning the toggle off with null bounds is exactly what the admin
    frontend sends — must not be rejected."""
    patch = SkuUpdate(
        variable_amount=False,
        min_amount_usd=None,
        max_amount_usd=None,
        rate_multiplier=None,
    )
    assert patch.variable_amount is False
    assert patch.min_amount_usd is None


# ---------- image URL SSRF guard ----------
#
# Full rule coverage (accept/reject matrix) lives in
# test_catalog_image_url_safety.py — these just confirm the validator is
# actually wired onto every image-carrying field on every schema.

_BRAND_BASE: dict[str, object] = {
    "slug": "steam",
    "category_id": "cat-1",
    "translations": [{"locale": "ru", "name": "Steam"}],
}
_PRODUCT_BASE: dict[str, object] = {
    "slug": "steam-wallet",
    "brand_id": "brand-1",
    "kind": "top_up",
    "translations": [{"locale": "ru", "name": "Steam Wallet"}],
}


@pytest.mark.parametrize("field", ["logo_url", "hero_image_url"])
def test_brand_create_rejects_ssrf_image_url(field: str) -> None:
    with pytest.raises(ValidationError, match="blocked network"):
        BrandCreate(**_BRAND_BASE, **{field: "https://10.0.0.1/x"})  # type: ignore[arg-type]


def test_brand_create_accepts_public_image_url() -> None:
    brand = BrandCreate(
        **_BRAND_BASE,  # type: ignore[arg-type]
        logo_url="https://cdn.example.com/logo.png",
    )
    assert brand.logo_url == "https://cdn.example.com/logo.png"


@pytest.mark.parametrize("field", ["logo_url", "hero_image_url"])
def test_brand_update_rejects_ssrf_image_url(field: str) -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        BrandUpdate(**{field: "https://localhost/x"})  # type: ignore[arg-type]


def test_brand_update_empty_string_still_clears_the_field() -> None:
    """ "" must keep passing through unvalidated — it's the established
    "clear this field" signal (admin_service.update_brand only skips
    ``None``, not ``""``)."""
    patch = BrandUpdate(logo_url="")
    assert patch.logo_url == ""


def test_product_create_rejects_ssrf_image_url() -> None:
    with pytest.raises(ValidationError, match="https"):
        ProductCreate(**_PRODUCT_BASE, image_url="file:///etc/passwd")  # type: ignore[arg-type]


def test_product_update_accepts_public_image_url() -> None:
    patch = ProductUpdate(image_url="https://cdn.example.com/box-art.png")
    assert patch.image_url == "https://cdn.example.com/box-art.png"


def test_sku_create_rejects_ssrf_image_url() -> None:
    with pytest.raises(ValidationError, match="blocked network"):
        SkuCreate(**_BASE_CREATE, image_url="https://169.254.169.254/latest/meta-data/")  # type: ignore[arg-type]


def test_sku_update_rejects_ssrf_image_url() -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        SkuUpdate(image_url="https://box.internal/x")
