"""Integration tests for ``brands.visible_retail`` (migration 0094, ADR-0095).

A brand with ``visible_retail = false`` and ``visible_b2b = true`` is reseller-only:
gone from every storefront read and refused at retail checkout, while the merchant
quote still sells it. ``active`` stays the master switch for both channels.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.integrations.player_check import check_player_for_brand
from yupay.modules.merchants.quote import load_orderable_sku
from yupay.modules.orders.schemas import OrderCreate, OrderItemIn
from yupay.modules.orders.service import Actor, create_order, quote_cart

pytestmark = pytest.mark.asyncio


async def _seed(db: AsyncSession, *, slug: str, visible_retail: bool) -> str:
    """One category → brand → product → SKU, visible to resellers. Returns the SKU id."""
    category = Category(
        id=new_id(),
        slug=f"{slug}-cat",
        sort_order=0,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug=slug,
        category_id=category.id,
        sort_order=0,
        active=True,
        visible_b2b=True,
        visible_retail=visible_retail,
        translations=[BrandTranslation(locale="ru", name=slug)],
    )
    sku = Sku(
        id=new_id(),
        sku_code=f"{slug}-60",
        denomination="60",
        price_usd=Decimal("1.00"),
        cost_usdt=Decimal("0.90"),
        sort_order=0,
        active=True,
        visible_b2b=True,
    )
    product = Product(
        id=new_id(),
        slug=f"{slug}-product",
        brand_id=brand.id,
        kind="top_up",
        sort_order=0,
        active=True,
        translations=[ProductTranslation(locale="ru", name=slug)],
        skus=[sku],
    )
    db.add_all([category, brand, product])
    await db.commit()
    return sku.id


async def test_new_brand_is_shown_to_customers(db_session: AsyncSession) -> None:
    """The column defaults to true, so no existing brand changes on migration."""
    sku_id = await _seed(db_session, slug="vr-default", visible_retail=True)
    sku = await load_orderable_sku(db_session, sku_id=sku_id)
    assert sku[0].product.brand.visible_retail is True


async def test_reseller_only_brand_is_gone_from_the_storefront(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Listing, brand page, product list and SKU lookup all miss it; a shown one lists."""
    hidden_sku = await _seed(db_session, slug="vr-hidden", visible_retail=False)
    await _seed(db_session, slug="vr-shown", visible_retail=True)

    brands = await client.get("/api/v1/catalog/brands")
    assert brands.status_code == 200
    slugs = {b["slug"] for b in brands.json()["items"]}
    assert "vr-shown" in slugs
    assert "vr-hidden" not in slugs

    assert (await client.get("/api/v1/catalog/brands/vr-hidden")).status_code == 404
    products = await client.get("/api/v1/catalog/products", params={"brand": "vr-hidden"})
    assert products.status_code == 200
    assert products.json()["items"] == []
    assert (await client.get("/api/v1/catalog/products/vr-hidden-product")).status_code == 404
    assert (await client.get(f"/api/v1/catalog/skus/{hidden_sku}")).status_code == 404


async def test_retail_checkout_refuses_a_reseller_only_brand(db_session: AsyncSession) -> None:
    """A known SKU id is not a way round the hidden catalogue — order or cart quote."""
    sku_id = await _seed(db_session, slug="vr-checkout", visible_retail=False)
    body = OrderCreate(items=[OrderItemIn(sku_id=sku_id, qty=1, fulfillment_data={})])

    with pytest.raises(ValidationError) as refused:
        await create_order(
            db_session,
            body,
            actor=Actor(user_id=None, email="buyer@example.com"),
            idempotency_key=f"vr-{new_id()}",
        )
    # The buyability gate itself, not some later check on the line.
    assert refused.value.extra == {"extra": {"sku_ids": [sku_id]}}
    with pytest.raises(ValidationError):
        await quote_cart(db_session, body)


async def test_reseller_still_buys_a_reseller_only_brand(db_session: AsyncSession) -> None:
    """The merchant quote ignores ``visible_retail``."""
    sku_id = await _seed(db_session, slug="vr-merchant", visible_retail=False)
    sku, _cost = await load_orderable_sku(db_session, sku_id=sku_id)
    assert sku.id == sku_id


async def test_storefront_player_check_misses_a_reseller_only_brand(
    db_session: AsyncSession,
) -> None:
    """The public check-player 404s before any supplier call."""
    await _seed(db_session, slug="vr-check", visible_retail=False)
    with pytest.raises(NotFoundError):
        await check_player_for_brand(
            db_session, brand_slug="vr-check", player_id="123", server_id=None
        )
