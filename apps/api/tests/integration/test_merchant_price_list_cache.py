"""The reseller price list is served from Redis for a minute.

Pins three things: a second read within the minute is the cached tree; a B2B
write through the merchants module drops it; a Redis that cannot be reached
costs nothing but the build.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import redis as core_redis
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Sku
from yupay.modules.merchants import admin as merchants_admin
from yupay.modules.merchants import price_list
from yupay.modules.merchants.models import Merchant

from tests.integration.test_merchant_api_read import _seed_brand

pytestmark = pytest.mark.asyncio


async def _seed(db: AsyncSession) -> tuple[Merchant, str]:
    """A merchant on the catalogue price and one b2b-visible SKU. Returns (merchant, sku_id)."""
    merchant = Merchant(id=new_id(), title="Cache LLC")
    db.add(merchant)
    ids = _seed_brand(db, n=1, skus=[{"sku_code": "cache-1", "denomination": "60 UC"}])
    await db.commit()
    return merchant, ids["cache-1"]


async def _unit_price(db: AsyncSession, merchant: Merchant) -> Decimal:
    out = await price_list.build(db, merchant=merchant)
    sku = out.brands[0].products[0].skus[0]
    assert sku.price_usd is not None  # a fixed-price SKU carries its price here
    return sku.price_usd


async def test_a_second_read_is_the_cached_tree(db_session: AsyncSession) -> None:
    merchant, sku_id = await _seed(db_session)
    first = await _unit_price(db_session, merchant)

    # A write behind the cache's back: the minute-old answer stands.
    await db_session.execute(
        update(Sku).where(Sku.id == sku_id).values(b2b_markup_pct=Decimal("50"))
    )
    await db_session.commit()
    assert await _unit_price(db_session, merchant) == first

    # A write through the module is seen at once.
    await merchants_admin.set_sku_b2b(db_session, sku_id=sku_id, markup_pct=Decimal("60"))
    await db_session.commit()
    assert await _unit_price(db_session, merchant) > first


async def test_every_merchant_on_the_catalogue_price_shares_one_entry(
    db_session: AsyncSession,
) -> None:
    merchant, _ = await _seed(db_session)
    await price_list.build(db_session, merchant=merchant)

    redis = core_redis.get_redis()
    keys = [k async for k in redis.scan_iter(match="merchants:price_list:*")]
    assert keys == ["merchants:price_list:0"]
    assert 0 < await redis.ttl(keys[0]) <= price_list.PRICE_LIST_TTL_SECONDS


async def test_a_dead_redis_still_answers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    merchant, _ = await _seed(db_session)

    class _Down:
        async def get(self, *_a: object, **_k: object) -> None:
            raise ConnectionError("redis down")

        set = get
        scan_iter = get

    monkeypatch.setattr(price_list, "get_redis", _Down)
    assert await _unit_price(db_session, merchant) > 0
    await price_list.invalidate()  # logs, never raises
