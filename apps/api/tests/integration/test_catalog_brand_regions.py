"""One game, many regions (ADR-0099): the storefront lists the main brand,
its page carries the regions, and reviews count towards the game."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.catalog.models import Brand
from yupay.modules.reviews import service as reviews_svc

from tests.integration.test_reviews_service import (
    _make_order,
    _make_published_review,
    _make_user,
    _seed_brand,
)

pytestmark = pytest.mark.asyncio


async def _region(db: AsyncSession, main: Brand, slug: str, code: str) -> tuple[Brand, object]:
    brand, sku = await _seed_brand(db, slug)
    brand.region_parent_id = main.id
    brand.region_code = code
    await db.flush()
    return brand, sku


async def test_regions_are_not_listed_but_their_game_is(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    main, _ = await _seed_brand(db_session, "mlx")
    await _region(db_session, main, "mlx-ru", "ru")
    await db_session.commit()

    slugs = {
        b["slug"] for b in (await integration_client.get("/api/v1/catalog/brands")).json()["items"]
    }
    assert "mlx" in slugs
    assert "mlx-ru" not in slugs


async def test_both_pages_carry_the_regions_in_switcher_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    main, _ = await _seed_brand(db_session, "mly")
    await _region(db_session, main, "mly-ph", "ph")
    await _region(db_session, main, "mly-ru", "ru")
    await db_session.commit()

    expected = [
        {"code": "global", "slug": "mly"},
        {"code": "ru", "slug": "mly-ru"},
        {"code": "ph", "slug": "mly-ph"},
    ]
    main_out = (await integration_client.get("/api/v1/catalog/brands/mly")).json()
    assert main_out["regions"] == expected
    assert main_out["region_code"] == "global"
    assert main_out["region_of"] is None

    ru_out = (await integration_client.get("/api/v1/catalog/brands/mly-ru")).json()
    assert ru_out["regions"] == expected
    assert ru_out["region_code"] == "ru"
    assert ru_out["region_of"] == "mly"


async def test_a_hidden_region_drops_off_the_switcher(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    main, _ = await _seed_brand(db_session, "mlz")
    hidden, _ = await _region(db_session, main, "mlz-tr", "tr")
    hidden.visible_retail = False
    await db_session.commit()

    out = (await integration_client.get("/api/v1/catalog/brands/mlz")).json()
    assert out["regions"] == []


async def test_a_review_from_a_regional_order_counts_for_the_game(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    main, _ = await _seed_brand(db_session, "mlr")
    ru, ru_sku = await _region(db_session, main, "mlr-ru", "ru")
    review = await _make_published_review(db_session, ru, ru_sku)  # type: ignore[arg-type]
    await db_session.commit()

    assert review.brand_id == main.id
    assert (await integration_client.get("/api/v1/catalog/brands/mlr")).json()["rating"] == {
        "avg": 5.0,
        "count": 1,
    }
    # The region's page shows the game's rating too.
    assert (await integration_client.get("/api/v1/catalog/brands/mlr-ru")).json()["rating"] == {
        "avg": 5.0,
        "count": 1,
    }


async def test_a_regional_order_is_reviewed_once_and_known_as_reviewed(
    db_session: AsyncSession,
) -> None:
    main, _ = await _seed_brand(db_session, "mlq")
    ru, ru_sku = await _region(db_session, main, "mlq-ru", "ru")
    user = await _make_user(db_session)
    order = await _make_order(db_session, user_id=user.id, sku_id=ru_sku.id)  # type: ignore[attr-defined]
    await reviews_svc.create_review(
        db_session,
        user_id=user.id,
        guest_email=None,
        order_id=order.id,
        brand_slug=ru.slug,
        rating=4,
        body=None,
        locale="ru",
    )
    slug, delivered, reviewed = await reviews_svc.review_eligibility(
        db_session, order_id=order.id, user_id=user.id, guest_email=None
    )
    assert (slug, delivered, reviewed) == ("mlq-ru", True, True)
