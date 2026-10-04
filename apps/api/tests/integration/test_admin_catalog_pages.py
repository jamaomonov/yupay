"""Admin catalogue reads at the post-import size: paged SKUs, single rows, totals.

The 2026-10 bulk import put 6150 SKUs, ~8600 mappings and ~4400 sourcing rules
behind endpoints that returned everything or truncated silently.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
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
)
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping
from yupay.modules.sourcing import service as sourcing

# The fixture registers under its own name whatever it is imported as.
from tests.integration.test_admin_catalog_routes import _grant_admin, _login

pytestmark = pytest.mark.asyncio

ADMIN = "00000000-0000-7000-8000-000000000001"


@pytest.fixture
async def admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    token = await _login(integration_client, tg_id=4242)
    await _grant_admin(db_session, tg_id=4242)
    return {"Authorization": f"Bearer {token}"}


async def _seed(db: AsyncSession, *, products: int, skus_each: int) -> tuple[str, list[str]]:
    """One brand with ``products`` products of ``skus_each`` SKUs. Returns (brand_id, sku_ids)."""
    category = Category(
        id=new_id(),
        slug=f"pg-{new_id()[:8]}",
        sort_order=0,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"pg-brand-{new_id()[:8]}",
        category_id=category.id,
        sort_order=0,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Paged", highlights=[])],
    )
    rows: list[Product] = []
    for p in range(products):
        rows.append(
            Product(
                id=new_id(),
                slug=f"pg-product-{p}-{new_id()[:6]}",
                brand_id=brand.id,
                kind="top_up",
                sort_order=p,
                active=True,
                translations=[ProductTranslation(locale="ru", name=f"Продукт {p}")],
                skus=[
                    Sku(
                        id=new_id(),
                        sku_code=f"pg-{p}-{i}-{new_id()[:6]}",
                        denomination=f"{(i + 1) * 10} Gems",
                        price_usd=Decimal("1.00"),
                        cost_usdt=Decimal("0.80"),
                        sort_order=i,
                        active=True,
                    )
                    for i in range(skus_each)
                ],
            )
        )
    db.add_all([category, brand, *rows])
    await db.commit()
    sku_ids = [s.id for product in rows for s in product.skus]
    return brand.id, sku_ids


async def test_skus_are_paged_by_product_with_a_total(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    brand_id, sku_ids = await _seed(db_session, products=3, skus_each=4)
    base = "/api/v1/admin/catalog/skus"

    page = await integration_client.get(
        base, headers=admin_headers, params={"brand_id": brand_id, "limit": 5}
    )
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["total"] == 12
    assert [s["sku_code"].split("-")[1] for s in body["items"]] == ["0", "0", "0", "0", "1"]

    tail = await integration_client.get(
        base, headers=admin_headers, params={"brand_id": brand_id, "limit": 5, "offset": 10}
    )
    assert len(tail.json()["items"]) == 2

    found = await integration_client.get(
        base, headers=admin_headers, params={"brand_id": brand_id, "q": "40 gems"}
    )
    assert found.json()["total"] == 3
    assert all(s["denomination"] == "40 Gems" for s in found.json()["items"])

    one = await integration_client.get(f"{base}/{sku_ids[0]}", headers=admin_headers)
    assert one.status_code == 200
    assert one.json()["id"] == sku_ids[0]


async def test_brand_and_product_read_one_row(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    brand_id, _ = await _seed(db_session, products=1, skus_each=1)
    brand = await integration_client.get(
        f"/api/v1/admin/catalog/brands/{brand_id}", headers=admin_headers
    )
    assert brand.status_code == 200
    assert brand.json()["id"] == brand_id
    products = await integration_client.get(
        "/api/v1/admin/catalog/products", headers=admin_headers, params={"brand_id": brand_id}
    )
    product_id = products.json()[0]["id"]
    product = await integration_client.get(
        f"/api/v1/admin/catalog/products/{product_id}", headers=admin_headers
    )
    assert product.status_code == 200
    assert product.json()["brand_id"] == brand_id
    missing = await integration_client.get(
        f"/api/v1/admin/catalog/brands/{new_id()}", headers=admin_headers
    )
    assert missing.status_code == 404


async def test_mappings_and_rules_page_with_a_total(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    _, sku_ids = await _seed(db_session, products=1, skus_each=3)
    for sku_id in sku_ids:
        await upsert_mapping(
            db_session,
            MappingUpsert(
                sku_id=sku_id,
                supplier_slug="g2b",
                kind="game",
                external_product_id="pgm",
                external_variant_id="60",
                quantity=1,
                extra={},
                is_active=True,
                updated_by="t",
            ),
        )
        await sourcing.set_rule(
            db_session, sku_id=sku_id, mode="force_supplier", supplier_slug="g2b", admin_id=ADMIN
        )
    await db_session.commit()

    mappings = await integration_client.get(
        "/api/v1/admin/integrations/mappings",
        headers=admin_headers,
        params={"supplier_slug": "g2b", "limit": 2, "offset": 1},
    )
    assert mappings.status_code == 200, mappings.text
    assert mappings.json()["total"] >= 3
    assert len(mappings.json()["items"]) == 2

    rules = await integration_client.get(
        "/api/v1/admin/sourcing/rules", headers=admin_headers, params={"limit": 2, "offset": 2}
    )
    assert rules.status_code == 200, rules.text
    assert rules.json()["total"] >= 3
    assert 1 <= len(rules.json()["items"]) <= 2


async def test_rules_carry_the_sku_label_and_mapped_products_are_listed(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    brand_id, sku_ids = await _seed(db_session, products=1, skus_each=2)
    await upsert_mapping(
        db_session,
        MappingUpsert(
            sku_id=sku_ids[0],
            supplier_slug="fzr",
            kind="game",
            external_product_id="pg_cat",
            external_variant_id="10_gems",
            quantity=1,
            extra={},
            is_active=True,
            updated_by="t",
        ),
    )
    await sourcing.set_rule(
        db_session, sku_id=sku_ids[0], mode="force_supplier", supplier_slug="fzr", admin_id=ADMIN
    )
    await db_session.commit()

    rules = await integration_client.get("/api/v1/admin/sourcing/rules", headers=admin_headers)
    rule = next(r for r in rules.json()["items"] if r["sku_id"] == sku_ids[0])
    assert rule["brand_id"] == brand_id
    assert rule["brand_name"] == "Paged"
    assert rule["denomination"] == "10 Gems"
    assert rule["product_slug"].startswith("pg-product-0")

    ids = await integration_client.get(
        "/api/v1/admin/integrations/mappings/products",
        headers=admin_headers,
        params={"supplier_slug": "fzr", "kind": "game"},
    )
    assert ids.status_code == 200, ids.text
    assert "pg_cat" in ids.json()["items"]

    off = await integration_client.get(
        "/api/v1/admin/catalog/skus",
        headers=admin_headers,
        params={"brand_id": brand_id, "active": "false"},
    )
    assert off.json()["total"] == 0
