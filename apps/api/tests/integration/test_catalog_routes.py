"""Integration tests for ``/api/v1/catalog/*`` routes.

Spins a minimal catalog (Category → Brand → Product → SKUs) directly through the ORM
into the testcontainers Postgres, then exercises the HTTP layer.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
    SkuPrice,
)

pytestmark = pytest.mark.asyncio


_PLAYER_ID_FIELD = {
    "key": "player_id",
    "label": {"ru": "ID игрока", "en": "Player ID", "uz": "Oʻyinchi ID"},
    "type": "text",
    "required": True,
}


@pytest.fixture
async def _seed_one(db_session: AsyncSession):
    """Insert one Category → Brand → Product → 2 SKUs (one with an RUB override)."""
    category = Category(
        id=new_id(),
        slug="games",
        icon="gamepad",
        sort_order=10,
        active=True,
        translations=[
            CategoryTranslation(locale="ru", name="Игры", description="Тест"),
            CategoryTranslation(locale="en", name="Games", description="Test"),
        ],
    )
    brand = Brand(
        id=new_id(),
        slug="pubg-mobile",
        category_id=category.id,
        logo_url=None,
        hero_image_url=None,
        accent_color="#F2A900",
        sort_order=10,
        active=True,
        translations=[
            BrandTranslation(locale="ru", name="PUBG Mobile", short_description="Тест"),
            BrandTranslation(locale="en", name="PUBG Mobile", short_description="Test"),
        ],
    )
    sku_with_override = Sku(
        id=new_id(),
        sku_code="pubg-uc-60-tr",
        denomination="60 UC",
        region="TR",
        price_usd=Decimal("0.85"),
        sort_order=10,
        active=True,
    )
    sku_plain = Sku(
        id=new_id(),
        sku_code="pubg-uc-300-tr",
        denomination="300 UC",
        region="TR",
        price_usd=Decimal("4.20"),
        sort_order=20,
        active=True,
    )
    product = Product(
        id=new_id(),
        slug="pubg-uc",
        brand_id=brand.id,
        kind="top_up",
        supplier_hint="codashop",
        image_url=None,
        sort_order=10,
        active=True,
        required_fields=[_PLAYER_ID_FIELD],
        translations=[
            ProductTranslation(locale="ru", name="UC", short_description="RU desc"),
            ProductTranslation(locale="en", name="UC", short_description="EN desc"),
        ],
        skus=[sku_with_override, sku_plain],
    )
    db_session.add(category)
    db_session.add(brand)
    db_session.add(product)
    await db_session.flush()
    db_session.add(SkuPrice(sku_id=sku_with_override.id, currency="RUB", price=Decimal("99.00")))
    await db_session.commit()
    return product


async def test_categories_default_locale(integration_client: AsyncClient, _seed_one) -> None:
    r = await integration_client.get("/api/v1/catalog/categories")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"][0]["slug"] == "games"
    assert body["items"][0]["name"] == "Игры"


async def test_categories_with_accept_language_en(
    integration_client: AsyncClient, _seed_one
) -> None:
    r = await integration_client.get(
        "/api/v1/catalog/categories", headers={"Accept-Language": "en-US,en;q=0.9"}
    )
    assert r.status_code == 200
    assert r.json()["items"][0]["name"] == "Games"


async def test_brands_filtered_by_category(integration_client: AsyncClient, _seed_one) -> None:
    r = await integration_client.get("/api/v1/catalog/brands?category=games")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["slug"] == "pubg-mobile"
    assert items[0]["category_slug"] == "games"


async def test_brand_detail_returns_products(integration_client: AsyncClient, _seed_one) -> None:
    r = await integration_client.get("/api/v1/catalog/brands/pubg-mobile")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == "pubg-mobile"
    assert body["accent_color"] == "#F2A900"
    assert len(body["products"]) == 1
    assert body["products"][0]["slug"] == "pubg-uc"


async def test_brand_detail_unknown_returns_404(integration_client: AsyncClient, _seed_one) -> None:
    r = await integration_client.get("/api/v1/catalog/brands/no-such-brand")
    assert r.status_code == 404


async def test_products_filtered_by_brand(integration_client: AsyncClient, _seed_one) -> None:
    r = await integration_client.get("/api/v1/catalog/products?brand=pubg-mobile")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["brand_slug"] == "pubg-mobile"
    assert body["items"][0]["starting_price_usd"] == "0.850000"


async def test_products_filtered_by_category(integration_client: AsyncClient, _seed_one) -> None:
    r = await integration_client.get("/api/v1/catalog/products?category=games")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["slug"] == "pubg-uc"
    assert items[0]["category_slug"] == "games"


async def _hide_brand(db_session: AsyncSession, slug: str) -> None:
    await db_session.execute(update(Brand).where(Brand.slug == slug).values(active=False))
    await db_session.commit()


async def test_hidden_brands_products_do_not_list(
    integration_client: AsyncClient, _seed_one, db_session: AsyncSession
) -> None:
    """A product under a hidden brand disappears from every listing — the plain
    list, its category, and even a direct ?brand=<slug> query."""
    await _hide_brand(db_session, "pubg-mobile")
    for path in (
        "/api/v1/catalog/products",
        "/api/v1/catalog/products?category=games",
        "/api/v1/catalog/products?brand=pubg-mobile",
    ):
        r = await integration_client.get(path)
        assert r.status_code == 200, r.text
        assert r.json()["items"] == [], path


async def test_product_detail_carries_brand_and_form(
    integration_client: AsyncClient, _seed_one
) -> None:
    r = await integration_client.get("/api/v1/catalog/products/pubg-uc")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["brand"]["slug"] == "pubg-mobile"
    assert body["category_slug"] == "games"
    assert len(body["skus"]) == 2
    assert body["skus"][0]["sku_code"] == "pubg-uc-60-tr"
    assert body["skus"][0]["display_price"] is None  # no currency requested
    # form schema is returned as-is
    assert body["required_fields"][0]["key"] == "player_id"
    assert body["required_fields"][0]["type"] == "text"


async def test_product_detail_with_currency_override(
    integration_client: AsyncClient, _seed_one
) -> None:
    r = await integration_client.get("/api/v1/catalog/products/pubg-uc?currency=RUB")
    assert r.status_code == 200
    body = r.json()
    first = body["skus"][0]
    # SKU has an explicit RUB override; FX failure on the other SKU must not blank it.
    assert first["display_price"]["currency"] == "RUB"
    assert first["display_price"]["source"] == "override"
    assert Decimal(first["display_price"]["amount"]) == Decimal("99")


async def test_product_detail_unknown_returns_404(
    integration_client: AsyncClient, _seed_one
) -> None:
    r = await integration_client.get("/api/v1/catalog/products/nope-nope")
    assert r.status_code == 404


async def test_product_detail_404s_when_brand_inactive(
    integration_client: AsyncClient, _seed_one, db_session: AsyncSession
) -> None:
    """An active product under a hidden brand must not leak by direct slug —
    the listing already hides it, but the detail endpoint has to as well."""
    # Product stays active; only the parent brand is hidden (staging pattern).
    await db_session.execute(update(Brand).where(Brand.slug == "pubg-mobile").values(active=False))
    await db_session.commit()
    r = await integration_client.get("/api/v1/catalog/products/pubg-uc")
    assert r.status_code == 404


async def test_sku_detail_404s_when_brand_inactive(
    integration_client: AsyncClient, _seed_one, db_session: AsyncSession
) -> None:
    """A SKU under a hidden brand must not resolve by id either — checkout
    verifies the price through this endpoint."""
    sku_id = _seed_one.skus[0].id
    ok = await integration_client.get(f"/api/v1/catalog/skus/{sku_id}")
    assert ok.status_code == 200, ok.text
    await db_session.execute(update(Brand).where(Brand.slug == "pubg-mobile").values(active=False))
    await db_session.commit()
    r = await integration_client.get(f"/api/v1/catalog/skus/{sku_id}")
    assert r.status_code == 404


async def test_unsupported_currency_falls_back_to_usd_only(
    integration_client: AsyncClient, _seed_one
) -> None:
    r = await integration_client.get("/api/v1/catalog/products/pubg-uc?currency=XYZ")
    assert r.status_code == 200
    assert r.json()["skus"][0]["display_price"] is None


async def test_sku_lookup(integration_client: AsyncClient, _seed_one) -> None:
    product = _seed_one
    sku_id = product.skus[0].id
    r = await integration_client.get(f"/api/v1/catalog/skus/{sku_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["sku_code"] == "pubg-uc-60-tr"
