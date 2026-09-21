"""Cost for a gift card, where the price lives one level down.

Both suppliers we buy codes from sell them as a **ladder under a product**:
NOVA as cards inside a gift-card category, G-Engine as denominations inside
a shop product. Before 2026-09-21 neither had a price anywhere in our system
— NOVA's voucher mappings were sent to the top-up endpoint, which 404s on a
gift-card category id, and G-Engine had no price lookup at all — so the
brand-comparison screen showed a blank for every SKU mapped to them and the
hourly refresh moved nothing.

The lookup reads ``supplier_catalog_cache``, and what makes that non-trivial
is the key: ``parent_external_id`` joined the primary key in 0084 because a
denomination id is unique per product, not per supplier. A lookup that omits
it is a guess, and these tests seed a same-id row under a different parent so
a guess fails.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
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
from yupay.modules.integrations.cost_refresh import refresh_sku_cost_for_mapping
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.service import upsert_catalog_entry

pytestmark = pytest.mark.asyncio


async def _seed_sku(db: AsyncSession, suffix: str) -> str:
    category = Category(
        id=new_id(),
        slug=f"cat-{suffix}",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Cat")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"br-{suffix}",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Br")],
    )
    product = Product(
        id=new_id(),
        slug=f"prod-{suffix}",
        brand_id=brand.id,
        kind="voucher",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sk-{suffix}",
        denomination="50",
        region="GLOBAL",
        price_usd=Decimal("1.00"),
        sort_order=10,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.commit()
    return sku.id


async def _mapping(
    db: AsyncSession,
    sku_id: str,
    *,
    supplier: str,
    product_id: str,
    variant: str,
    kind: str = "voucher",
) -> SkuSupplierMapping:
    """Persist the mapping and route the SKU to it.

    The rule matters: ``Sku.cost_usdt`` is only written by the supplier the
    SKU actually buys from, so without one every outcome here would come
    back "price recorded for comparison, cost belongs to whoever is routed"
    — true, and not what these tests are about.
    """
    from yupay.modules.sourcing import service as sourcing_svc

    mapping = SkuSupplierMapping(
        sku_id=sku_id,
        supplier_slug=supplier,
        kind=kind,
        external_product_id=product_id,
        external_variant_id=variant,
        quantity=1,
        extra={},
        is_active=True,
    )
    db.add(mapping)
    await db.commit()
    await sourcing_svc.set_rule(
        db, sku_id=sku_id, mode="force_supplier", supplier_slug=supplier, admin_id="test-admin"
    )
    await db.commit()
    return mapping


async def test_a_nova_gift_card_is_priced_from_its_card_row(db_session: AsyncSession) -> None:
    sku_id = await _seed_sku(db_session, "nova-card")
    await upsert_catalog_entry(
        db_session,
        supplier_slug="nova",
        kind="voucher_denom",
        external_id="50_robux",
        title="50 Robux",
        raw={"card_id": "50_robux", "stock": 10922},
        parent_external_id="roblox_global",
        price_usdt=Decimal("0.878730"),
    )
    # The same card id under another category, at another price. A lookup
    # that drops the parent would be free to pick this one.
    await upsert_catalog_entry(
        db_session,
        supplier_slug="nova",
        kind="voucher_denom",
        external_id="50_robux",
        title="50 Robux (other)",
        raw={},
        parent_external_id="roblox_brazil",
        price_usdt=Decimal("99.000000"),
    )
    await db_session.commit()

    mapping = await _mapping(
        db_session, sku_id, supplier="nova", product_id="roblox_global", variant="50_robux"
    )
    outcome = await refresh_sku_cost_for_mapping(db_session, mapping=mapping)

    assert outcome.reason is None, outcome.reason
    assert outcome.wrote_cost is True
    assert Decimal(str(outcome.new_cost)) == Decimal("0.878730")


async def test_a_gengine_shop_denomination_is_priced_from_its_row(
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_sku(db_session, "gengine-shop")
    await upsert_catalog_entry(
        db_session,
        supplier_slug="gengine",
        kind="voucher_denom",
        external_id="727",
        title="2000 Robux",
        raw={"id": 727, "stock": 10},
        parent_external_id="9",
        price_usdt=Decimal("22.0932"),
    )
    await db_session.commit()

    mapping = await _mapping(db_session, sku_id, supplier="gengine", product_id="9", variant="727")
    outcome = await refresh_sku_cost_for_mapping(db_session, mapping=mapping)

    assert outcome.reason is None, outcome.reason
    assert outcome.wrote_cost is True
    assert Decimal(str(outcome.new_cost)) == Decimal("22.0932")


async def test_a_gengine_recharge_denomination_reads_the_game_ladder(
    db_session: AsyncSession,
) -> None:
    """Shop product 9 is Roblox Global; recharge service 9 is Delta Force.

    Same id, two catalogues, two prices — told apart by ``kind`` alone. This
    is the collision the fourth cache kind exists for, so it is pinned with
    both rows present at once.
    """
    sku_id = await _seed_sku(db_session, "gengine-recharge")
    await upsert_catalog_entry(
        db_session,
        supplier_slug="gengine",
        kind="voucher_denom",
        external_id="29",
        title="1480 Delta Coin (shop)",
        raw={},
        parent_external_id="9",
        price_usdt=Decimal("111.000000"),
    )
    await upsert_catalog_entry(
        db_session,
        supplier_slug="gengine",
        kind="game_denom",
        external_id="29",
        title="1480 Delta Coin",
        raw={"id": 29},
        parent_external_id="9",
        price_usdt=Decimal("18.400000"),
    )
    await db_session.commit()

    mapping = await _mapping(
        db_session, sku_id, supplier="gengine", product_id="9", variant="29", kind="game"
    )
    outcome = await refresh_sku_cost_for_mapping(db_session, mapping=mapping)

    assert outcome.reason is None, outcome.reason
    assert Decimal(str(outcome.new_cost)) == Decimal("18.400000")


async def test_an_unsynced_catalogue_says_so_rather_than_guessing(
    db_session: AsyncSession,
) -> None:
    """The cache is the price source, so an empty cache is an actionable
    message and not a silent zero — «синхронизируйте каталог» is a button
    the operator has."""
    sku_id = await _seed_sku(db_session, "gengine-unsynced")

    mapping = await _mapping(db_session, sku_id, supplier="gengine", product_id="9", variant="727")
    outcome = await refresh_sku_cost_for_mapping(db_session, mapping=mapping)

    assert outcome.new_cost is None
    assert "синхронизируйте каталог" in (outcome.reason or "")
