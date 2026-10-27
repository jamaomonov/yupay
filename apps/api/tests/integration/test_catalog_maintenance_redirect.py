"""A brand in maintenance points its buyers at another brand selling the same goods.

Standoff 2 promo codes are paused while G-Engine is down; the page keeps its search
traffic and links to Standoff 2 Gold by player id (2026-10-27).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_reviews_service import _seed_brand

pytestmark = pytest.mark.asyncio


async def test_a_paused_brand_links_to_the_live_one(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    paused, _ = await _seed_brand(db_session, "so-promo")
    live, _ = await _seed_brand(db_session, "so-id")
    paused.maintenance = True
    paused.maintenance_redirect_id = live.id
    await db_session.commit()

    out = (await integration_client.get("/api/v1/catalog/brands/so-promo")).json()

    assert out["maintenance"] is True
    assert out["maintenance_redirect"]["slug"] == "so-id"
    assert out["maintenance_redirect"]["name"]


async def test_no_link_once_the_brand_is_back_or_the_target_is_not_buyable(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    paused, _ = await _seed_brand(db_session, "so-promo-2")
    live, _ = await _seed_brand(db_session, "so-id-2")
    paused.maintenance_redirect_id = live.id
    await db_session.commit()

    back = (await integration_client.get("/api/v1/catalog/brands/so-promo-2")).json()

    paused.maintenance = True
    live.maintenance = True
    await db_session.commit()
    dead_end = (await integration_client.get("/api/v1/catalog/brands/so-promo-2")).json()

    assert back["maintenance_redirect"] is None, "not in maintenance: no link"
    assert dead_end["maintenance_redirect"] is None, "never link to another paused brand"
