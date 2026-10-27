"""One game sold two ways, each on its own page (migration 0108).

Standoff 2: Gold by player id is the main variant and the catalogue tile; promo
codes keep their own page (and its search history). Both pages list both.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_reviews_service import _seed_brand

pytestmark = pytest.mark.asyncio


async def test_the_catalogue_lists_the_main_variant_and_both_pages_link_each_other(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    main, _ = await _seed_brand(db_session, "sv-id")
    promo, _ = await _seed_brand(db_session, "sv-promo")
    main.variant_code = "id"
    promo.variant_parent_id = main.id
    promo.variant_code = "promo"
    await db_session.commit()

    listed = {
        b["slug"] for b in (await integration_client.get("/api/v1/catalog/brands")).json()["items"]
    }
    with_variants = {
        b["slug"]
        for b in (await integration_client.get("/api/v1/catalog/brands?variants=true")).json()[
            "items"
        ]
    }
    expected = [{"code": "id", "slug": "sv-id"}, {"code": "promo", "slug": "sv-promo"}]
    main_out = (await integration_client.get("/api/v1/catalog/brands/sv-id")).json()
    promo_out = (await integration_client.get("/api/v1/catalog/brands/sv-promo")).json()

    assert "sv-id" in listed
    assert "sv-promo" not in listed, "one tile per game"
    assert {"sv-id", "sv-promo"} <= with_variants, "the sitemap still sees both pages"
    assert main_out["variants"] == expected
    assert promo_out["variants"] == expected
    assert promo_out["slug"] == "sv-promo", "a variant keeps its own page"


async def test_a_hidden_variant_leaves_no_switcher(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    main, _ = await _seed_brand(db_session, "sw-id")
    promo, _ = await _seed_brand(db_session, "sw-promo")
    main.variant_code = "id"
    promo.variant_parent_id = main.id
    promo.variant_code = "promo"
    promo.visible_retail = False
    await db_session.commit()

    out = (await integration_client.get("/api/v1/catalog/brands/sw-id")).json()

    assert out["variants"] == []
