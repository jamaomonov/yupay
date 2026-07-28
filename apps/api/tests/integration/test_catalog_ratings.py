"""Catalog brand DTOs carry the reviews aggregate, batched (no N+1)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.catalog import service as catalog_svc

from tests.integration.test_reviews_service import _make_published_review, _seed_brand

pytestmark = pytest.mark.asyncio


async def test_brand_grid_includes_rating(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    brand, sku = await _seed_brand(db_session, "steam")
    await _make_published_review(db_session, brand, sku)
    await db_session.commit()

    r = await integration_client.get("/api/v1/catalog/brands")
    item = next(b for b in r.json()["items"] if b["slug"] == "steam")
    assert item["rating"] is not None
    assert item["rating"]["count"] == 1
    assert item["rating"]["avg"] == 5.0


async def test_brand_detail_includes_rating(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    brand, sku = await _seed_brand(db_session, "pubg")
    await _make_published_review(db_session, brand, sku)
    await db_session.commit()

    r = await integration_client.get("/api/v1/catalog/brands/pubg")
    assert r.json()["rating"] == {"avg": 5.0, "count": 1}


async def test_unreviewed_brand_has_null_rating(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_brand(db_session, "roblox")
    await db_session.commit()
    r = await integration_client.get("/api/v1/catalog/brands/roblox")
    assert r.json()["rating"] is None


async def test_list_brands_rating_is_not_n_plus_1(db_session: AsyncSession) -> None:
    for slug in ("b1", "b2", "b3", "b4"):
        brand, sku = await _seed_brand(db_session, slug)
        await _make_published_review(db_session, brand, sku)
    # Commit the seed so no pending writes autoflush during the measured call
    # (mirrors the real request path, where each request commits its own work).
    await db_session.commit()

    stats_queries = 0

    @event.listens_for(db_session.bind.sync_engine, "before_cursor_execute")
    def _count(conn, cursor, statement, params, context, executemany):  # type: ignore[no-untyped-def]
        nonlocal stats_queries
        if "brand_rating_stats" in statement:
            stats_queries += 1

    brands = await catalog_svc.list_brands(db_session, locale="ru")

    reviewed = [b for b in brands if b.rating is not None]
    assert len(reviewed) == 4
    # One batched stats query regardless of brand count (no N+1).
    assert stats_queries == 1
