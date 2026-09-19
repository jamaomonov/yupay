"""Regression test for the FX manual-override read amplification.

Sentry breadcrumbs on a production 500 (``GET /catalog/products/pubg-uc?currency=UZS``)
showed three ``GET 'fx:manual:UZS'`` inside 50ms of one request: ``_resolve_price`` runs
once per SKU, and each call used to re-read the same admin override from Redis, so a
35-SKU product page read one invariant key dozens of times per view — wasted round
trips, and dozens of chances to hit a Redis blip instead of one.

The fix threads a caller-owned ``override_cache`` dict through ``_resolve_price`` (the
same pattern already used for ``rate_cache``, the guarded market rate) so the override
is read once per request and reused. This test seeds a product with several fixed-price
SKUs and pins the actual Redis read count for ``fx:manual:{quote}`` at 1, regardless of
how many SKUs the page renders — the regression that would otherwise creep back.
"""

from __future__ import annotations

from decimal import Decimal

import fakeredis.aioredis
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.catalog.service import get_product_by_slug
from yupay.modules.fx.providers.base import FxProvider, Quote
from yupay.modules.fx.service import FxService

pytestmark = pytest.mark.asyncio


class _StubProvider(FxProvider):
    """Always answers a fixed USD->RUB rate."""

    name = "stub"

    def supports(self, base: str, quote: str) -> bool:
        return base.upper() == "USD" and quote.upper() == "RUB"

    async def get_rate(self, base: str, quote: str) -> Quote:
        return Quote(base="USD", quote="RUB", rate=Decimal("90"), fetched_at=now(), source="stub")


@pytest.fixture
async def _many_sku_product(db_session: AsyncSession) -> str:
    """A product with 6 active, fixed-price, no-override SKUs — every one of
    them must go through ``_resolve_fx_price`` on a non-USD request."""
    category = Category(id=new_id(), slug="games-many", sort_order=10, active=True)
    brand = Brand(
        id=new_id(), slug="many-sku-brand", category_id=category.id, sort_order=10, active=True
    )
    skus = [
        Sku(
            id=new_id(),
            sku_code=f"denom-{i}",
            denomination=f"{i} UC",
            region=None,
            price_usd=Decimal("1.00") * i,
            sort_order=i,
            active=True,
        )
        for i in range(1, 7)
    ]
    product = Product(
        id=new_id(),
        slug="many-sku-product",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        skus=skus,
    )
    db_session.add(category)
    db_session.add(brand)
    db_session.add(product)
    await db_session.commit()
    return product.slug


async def test_product_page_reads_the_manual_override_once_for_n_skus(
    db_session: AsyncSession, _many_sku_product: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    fx = FxService(providers=[_StubProvider()], redis=redis)

    calls: list[str] = []
    orig_get = redis.get

    async def _counting_get(key, *a, **kw):  # type: ignore[no-untyped-def]
        if isinstance(key, str) and key.startswith("fx:manual:"):
            calls.append(key)
        return await orig_get(key, *a, **kw)

    monkeypatch.setattr(redis, "get", _counting_get)

    detail = await get_product_by_slug(
        db_session, _many_sku_product, locale="ru", currency="RUB", fx=fx
    )

    assert detail is not None
    assert len(detail.skus) == 6
    # Every SKU actually resolved an FX price — otherwise this test would
    # trivially pass by never touching the override at all.
    assert all(s.display_price is not None and s.display_price.source == "fx" for s in detail.skus)

    assert calls == ["fx:manual:RUB"], (
        f"expected exactly one manual-override read for 6 SKUs, got {len(calls)}: {calls}"
    )
