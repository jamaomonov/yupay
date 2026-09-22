"""Which NOVA mapping rows the fulfiller will actually buy from.

This exists because the unit suite could not answer that. ``_mapping_for``'s
whole content is a WHERE clause, and the fake session next door
(``tests/unit/test_nova_fulfiller.py``) hands back whatever row the test gave
it no matter what was asked — so a wrong filter reads as a passing test.

A wrong filter is exactly what shipped. Between the gift-card adapter landing
(2026-09-21) and this file, ``_mapping_for`` selected ``kind == "game"``
alone, which made the ``kind == "voucher"`` branch at the top of ``fulfill``
unreachable: every NOVA gift-card order failed at our own guard with "no
active nova game mapping for this SKU", naming the wrong thing. It was found
by a customer's paid Roblox 50 order, not by a test.

So these run against a real database, where a WHERE clause means something.
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
from yupay.modules.fulfillment.suppliers.base import FulfillerError
from yupay.modules.fulfillment.suppliers.nova import _mapping_for
from yupay.modules.integrations.models import SkuSupplierMapping

pytestmark = pytest.mark.asyncio


async def _sku(db: AsyncSession, suffix: str) -> str:
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


async def _map(
    db: AsyncSession, sku_id: str, *, kind: str, active: bool = True, supplier: str = "nova"
) -> None:
    db.add(
        SkuSupplierMapping(
            sku_id=sku_id,
            supplier_slug=supplier,
            kind=kind,
            external_product_id="roblox_global",
            external_variant_id="50_robux",
            quantity=1,
            extra={},
            is_active=active,
        )
    )
    await db.commit()


async def test_a_gift_card_mapping_is_found(db_session: AsyncSession) -> None:
    """The regression. A NOVA voucher mapping is a route this adapter buys."""
    sku_id = await _sku(db_session, "nova-voucher")
    await _map(db_session, sku_id, kind="voucher")

    row = await _mapping_for(db_session, sku_id=sku_id)

    assert row.kind == "voucher"
    assert row.external_variant_id == "50_robux"


async def test_a_top_up_mapping_is_found(db_session: AsyncSession) -> None:
    sku_id = await _sku(db_session, "nova-game")
    await _map(db_session, sku_id, kind="game")

    row = await _mapping_for(db_session, sku_id=sku_id)

    assert row.kind == "game"


async def test_a_gift_kind_is_still_not_a_nova_route(db_session: AsyncSession) -> None:
    """The filter stays a filter. `gift` is Waxpeer's Steam shape and means
    nothing to NOVA — failing at our own guard beats failing at theirs with
    whatever they say about an id from the wrong namespace."""
    sku_id = await _sku(db_session, "nova-gift")
    await _map(db_session, sku_id, kind="gift")

    with pytest.raises(FulfillerError) as excinfo:
        await _mapping_for(db_session, sku_id=sku_id)

    assert "kind=game or kind=voucher" in str(excinfo.value)


async def test_a_deactivated_mapping_is_not_a_route(db_session: AsyncSession) -> None:
    sku_id = await _sku(db_session, "nova-inactive")
    await _map(db_session, sku_id, kind="voucher", active=False)

    with pytest.raises(FulfillerError):
        await _mapping_for(db_session, sku_id=sku_id)


async def test_another_suppliers_mapping_is_not_a_route(db_session: AsyncSession) -> None:
    sku_id = await _sku(db_session, "nova-other-supplier")
    await _map(db_session, sku_id, kind="voucher", supplier="gengine")

    with pytest.raises(FulfillerError):
        await _mapping_for(db_session, sku_id=sku_id)
