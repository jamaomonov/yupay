"""``/skins/facets?category=``: the weapon row lists the whole category, not one page,
and wear/rarity counts match the grid the customer is looking at (plan 2c, Task 1)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.core.ids import new_id
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.naming import slug_for

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CS2_SKINS_ENABLED", "true")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _row(name: str, category: str, weapon: str | None, ext: str | None, **kw: object) -> SkinItem:
    return SkinItem(
        id=new_id(),
        market_hash_name=name,
        phase="",
        slug=slug_for(name, ""),
        category=category,
        weapon=weapon,
        skin=name,
        exterior=ext,
        search_text=name.lower(),
        min_auto_units=1000,
        count_auto=kw.pop("count", 5),
        active=True,
        cheapest_auto=[{"listing_id": 1, "price_units": 1000}],
        **kw,
    )


@pytest.fixture
async def seeded(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            _row("Galil AR | A (Field-Tested)", "rifles", "Galil AR", "FT", count=90),
            _row(
                "AWP | B (Minimal Wear)",
                "rifles",
                "AWP",
                "MW",
                count=10,
                rarity="Covert",
                rarity_color="#eb4b4b",
            ),
            _row("AK-47 | C (Field-Tested)", "rifles", "AK-47", "FT", count=1),
            _row("Glock-18 | D (Factory New)", "pistols", "Glock-18", "FN", count=500),
            _row("Kilowatt Case", "cases", None, None, count=9000),
            _row("Cmdr. Mae | SWAT", "agents", None, None, team="ct", rarity="Master"),
            _row("Sir Bloody | Guerrilla", "agents", None, None, team="t", rarity="Superior"),
            _row("Bloody Darryl | The Professionals", "agents", None, None, team="t"),
        ]
    )
    await db_session.commit()


async def test_weapons_are_scoped_and_led_by_the_classics(
    integration_client: AsyncClient, seeded: None
) -> None:
    body = (await integration_client.get("/api/v1/skins/facets?category=rifles")).json()
    assert [w["value"] for w in body["weapons"]] == ["AK-47", "AWP", "Galil AR"]
    assert {e["value"]: e["count"] for e in body["exteriors"]} == {"FT": 2, "MW": 1}
    # The tile row still sees every category.
    assert {c["value"] for c in body["categories"]} == {"rifles", "pistols", "cases", "agents"}


async def test_rarities_carry_their_colour(integration_client: AsyncClient, seeded: None) -> None:
    body = (await integration_client.get("/api/v1/skins/facets?category=rifles")).json()
    assert body["rarities"] == [{"value": "Covert", "count": 1, "color": "#eb4b4b"}]


async def test_without_a_category_facets_stay_global(
    integration_client: AsyncClient, seeded: None
) -> None:
    body = (await integration_client.get("/api/v1/skins/facets")).json()
    assert "Glock-18" in [w["value"] for w in body["weapons"]]


async def test_rarities_run_from_rarest_to_commonest(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    for i, grade in enumerate(["Mil-Spec Grade", "Consumer Grade", "Covert", "Restricted"]):
        db_session.add(
            _row(f"P250 | S{i} (Field-Tested)", "pistols", "P250", "FT", count=90 - i, rarity=grade)
        )
    await db_session.commit()
    body = (await integration_client.get("/api/v1/skins/facets?category=pistols")).json()
    assert [r["value"] for r in body["rarities"]] == [
        "Covert",
        "Restricted",
        "Mil-Spec Grade",
        "Consumer Grade",
    ]


async def test_an_unknown_category_is_refused(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/skins/facets?category=bogus")
    assert r.status_code == 422


async def test_agents_count_their_sides(integration_client: AsyncClient, seeded: None) -> None:
    body = (await integration_client.get("/api/v1/skins/facets?category=agents")).json()
    assert body["teams"] == [{"value": "t", "count": 2}, {"value": "ct", "count": 1}]
    rifles = (await integration_client.get("/api/v1/skins/facets?category=rifles")).json()
    assert rifles["teams"] == []


async def test_the_catalogue_filters_agents_by_side(
    integration_client: AsyncClient, seeded: None
) -> None:
    body = (await integration_client.get("/api/v1/skins/catalog?category=agents&team=ct")).json()
    assert [i["name"] for i in body["items"]] == ["Cmdr. Mae | SWAT"]
    bad = await integration_client.get("/api/v1/skins/catalog?category=agents&team=zz")
    assert bad.status_code == 422
