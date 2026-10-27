"""A hand-filled SKU priced in roubles keeps a dollar cost that follows the rate.

Standoff 2 Gold has no supplier API: the operator buys it in the official store
for roubles. The price sits on the SKU's ``manual`` mapping and the refresh turns
it into ``Sku.cost_usdt`` at the current USD→RUB rate, so the margin holds as
the rouble moves. The order still goes to the manual queue.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

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
from yupay.modules.fx.providers.base import Quote
from yupay.modules.integrations.cost_refresh import refresh_sku_cost_for_mapping
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.sourcing import service as sourcing_svc

pytestmark = pytest.mark.asyncio


class _Fx:
    def __init__(self, rate: str) -> None:
        self.rate = Decimal(rate)

    async def get_rate(self, base: str, quote: str, **_: Any) -> Quote:
        return Quote(
            base=base, quote=quote, rate=self.rate, fetched_at=datetime.now(UTC), source="test"
        )


@pytest.fixture
def fx(monkeypatch: pytest.MonkeyPatch) -> _Fx:
    stub = _Fx("80")
    monkeypatch.setattr("yupay.modules.fx.factory.build_default_service", lambda **_: stub)
    return stub


async def _seed(db: AsyncSession, suffix: str, *, extra: dict[str, Any]) -> SkuSupplierMapping:
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
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sk-{suffix}",
        denomination="100 Gold",
        region="GLOBAL",
        price_usd=Decimal("1.00"),
        margin_percent=Decimal("9"),
        sort_order=10,
        active=True,
    )
    mapping = SkuSupplierMapping(
        sku_id=sku.id,
        supplier_slug="manual",
        kind="game",
        external_product_id="standoff2-store",
        external_variant_id="100",
        quantity=1,
        extra=extra,
        is_active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.flush()
    db.add(mapping)
    await db.commit()
    return mapping


async def test_a_rouble_price_becomes_the_dollar_cost(db_session: AsyncSession, fx: _Fx) -> None:
    mapping = await _seed(db_session, "rub-1", extra={"cost": "119", "cost_currency": "RUB"})

    decision = await sourcing_svc.resolve_for_sku(db_session, mapping.sku_id)
    outcome = await refresh_sku_cost_for_mapping(db_session, mapping=mapping)
    await db_session.commit()

    assert decision.primary == "supplier:manual", "the order still goes to the manual queue"
    assert outcome.wrote_cost, outcome.reason
    sku = await db_session.get(Sku, mapping.sku_id)
    assert sku is not None
    await db_session.refresh(sku)
    assert sku.cost_usdt == Decimal("1.487500")
    assert sku.price_usd >= Decimal("1.487500") * Decimal("1.09")
    assert outcome.source == "manual:RUB@80"


async def test_a_weaker_rouble_lowers_the_cost_but_not_the_shelf_price(
    db_session: AsyncSession, fx: _Fx
) -> None:
    mapping = await _seed(db_session, "rub-2", extra={"cost": "119", "cost_currency": "RUB"})
    await refresh_sku_cost_for_mapping(db_session, mapping=mapping)
    await db_session.commit()
    sku = await db_session.get(Sku, mapping.sku_id)
    assert sku is not None
    await db_session.refresh(sku)
    price_before = sku.price_usd

    fx.rate = Decimal("100")
    outcome = await refresh_sku_cost_for_mapping(
        db_session, mapping=mapping, allow_price_drop=False
    )
    await db_session.commit()
    await db_session.refresh(sku)

    assert outcome.updated
    assert sku.cost_usdt == Decimal("1.190000")
    assert sku.price_usd == price_before, "the hourly pass never lowers a price"


async def test_a_manual_mapping_without_a_price_writes_nothing(
    db_session: AsyncSession, fx: _Fx
) -> None:
    mapping = await _seed(db_session, "rub-3", extra={})

    outcome = await refresh_sku_cost_for_mapping(db_session, mapping=mapping)

    assert not outcome.wrote_cost
    assert outcome.reason == "у ручного маппинга не указана цена закупки"
