"""HTTP tests for ``GET /api/v1/skins/*``: the flag guard, pricing, filters,
keyset paging, search with a Russian alias, facets, detail. Waxpeer is never
called — everything is seeded straight into ``skin_items``."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.core.ids import new_id
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.quote_settings import ManualOverride
from yupay.modules.skins.models import SkinItem, SkinSearchAlias
from yupay.modules.skins.naming import search_text, slug_for

pytestmark = pytest.mark.asyncio
_UZS_RATE = Decimal("12700")


def _uzs(usd: str) -> str:
    """Default rules round UZS up to 100."""
    raw = Decimal(usd) * _UZS_RATE
    return str(((raw / 100).to_integral_value(rounding="ROUND_CEILING")) * 100)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CS2_SKINS_ENABLED", "true")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def _uzs_manual_rate(integration_client: AsyncClient) -> None:
    fx = build_default_service()
    await fx.publish_quote_setting(
        ManualOverride(quote="UZS", use_manual=True, manual_rate=_UZS_RATE, updated_at=None)
    )


def _item(name: str, *, category: str, units: int | None, count: int, **extra: Any) -> SkinItem:
    from yupay.modules.skins.naming import parse_market_name

    p = parse_market_name(name)
    return SkinItem(
        id=new_id(),
        market_hash_name=p.market_hash_name,
        phase=p.phase,
        slug=slug_for(p.market_hash_name, p.phase),
        category=category,
        weapon=p.weapon,
        skin=p.skin,
        exterior=p.exterior,
        stattrak=p.stattrak,
        souvenir=p.souvenir,
        search_text=search_text(p.market_hash_name, p.phase),
        min_auto_units=units,
        count_auto=count,
        cheapest_auto=[{"listing_id": 1, "price_units": units}] if units else [],
        active=count > 0,
        **extra,
    )


@pytest.fixture
async def seeded(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            _item(
                "AK-47 | Redline (Field-Tested)",
                category="rifles",
                units=27867,
                count=49,
                steam_price_units=43794,
            ),
            _item(
                "StatTrak™ AK-47 | Redline (Field-Tested)", category="rifles", units=80000, count=3
            ),
            _item("AWP | Asiimov (Field-Tested)", category="rifles", units=90000, count=20),
            _item(
                "Glock-18 | Water Elemental (Field-Tested)",
                category="pistols",
                units=20230,
                count=50,
            ),
            _item(
                "★ Karambit | Doppler Phase 2 (Factory New)",
                category="knives",
                units=1450000,
                count=1,
            ),
            _item("AWP | Manual Only (Field-Tested)", category="rifles", units=None, count=0),
            _item(
                "Sticker | Aerial (Foil) | Katowice 2019", category="stickers", units=4284, count=1
            ),
            SkinSearchAlias(alias="ак", text="ak-47"),
            SkinSearchAlias(alias="редлайн", text="redline"),
        ]
    )
    await db_session.commit()


async def test_routes_404_while_disabled(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CS2_SKINS_ENABLED", "false")
    cfg.get_settings.cache_clear()
    for path in ("/api/v1/skins/catalog", "/api/v1/skins/facets", "/api/v1/skins/suggest?q=ak"):
        assert (await integration_client.get(path)).status_code == 404


async def test_catalog_prices_and_hides_sold_out_and_hidden_categories(
    integration_client: AsyncClient, seeded: None
) -> None:
    r = await integration_client.get("/api/v1/skins/catalog")
    assert r.status_code == 200
    body = r.json()
    names = [i["name"] for i in body["items"]]
    assert "AWP | Manual Only (Field-Tested)" not in names  # inactive
    assert "Sticker | Aerial (Foil) | Katowice 2019" not in names  # category not enabled
    ak = next(i for i in body["items"] if i["slug"] == "ak-47-redline-field-tested")
    # brackets 1.80069 + (3 % expenses - 0.5 pp for 49 listings) × 27.867 = 2.4974 -> 30.37
    assert ak["price_usd"] == "30.37"
    assert ak["price_uzs"] == _uzs("30.37")
    assert ak["discount_percent"] == 31
    assert ak["count"] == 49
    assert names[0] == "Glock-18 | Water Elemental (Field-Tested)"  # cheapest first


async def test_filters_and_keyset_paging(integration_client: AsyncClient, seeded: None) -> None:
    r = await integration_client.get(
        "/api/v1/skins/catalog", params={"category": "rifles", "limit": 2}
    )
    first = r.json()
    assert [i["name"] for i in first["items"]] == [
        "AK-47 | Redline (Field-Tested)",
        "StatTrak™ AK-47 | Redline (Field-Tested)",
    ]
    assert first["next_cursor"]
    r = await integration_client.get(
        "/api/v1/skins/catalog",
        params={"category": "rifles", "limit": 2, "cursor": first["next_cursor"]},
    )
    second = r.json()
    assert [i["name"] for i in second["items"]] == ["AWP | Asiimov (Field-Tested)"]
    assert second["next_cursor"] is None
    r = await integration_client.get(
        "/api/v1/skins/catalog", params={"weapon": "AK-47", "stattrak": "true"}
    )
    assert [i["name"] for i in r.json()["items"]] == ["StatTrak™ AK-47 | Redline (Field-Tested)"]
    r = await integration_client.get("/api/v1/skins/catalog", params={"cursor": "garbage"})
    assert r.status_code == 422


async def test_search_with_a_russian_alias(integration_client: AsyncClient, seeded: None) -> None:
    r = await integration_client.get("/api/v1/skins/catalog", params={"q": "ак 47 редлайн"})
    names = [i["name"] for i in r.json()["items"]]
    assert names[0] == "AK-47 | Redline (Field-Tested)"
    r = await integration_client.get("/api/v1/skins/suggest", params={"q": "asiim"})
    assert [i["slug"] for i in r.json()["items"]] == ["awp-asiimov-field-tested"]
    r = await integration_client.get("/api/v1/skins/catalog", params={"q": "zzzz nothing"})
    assert r.status_code == 200
    assert r.json()["items"] == []


async def test_facets_count_only_active_enabled_rows(
    integration_client: AsyncClient, seeded: None
) -> None:
    body = (await integration_client.get("/api/v1/skins/facets")).json()
    assert {f["value"]: f["count"] for f in body["categories"]} == {
        "rifles": 3,
        "pistols": 1,
        "knives": 1,
    }
    assert {"value": "FT", "count": 4} in body["exteriors"]


async def test_detail_has_phase_and_cheapest(integration_client: AsyncClient, seeded: None) -> None:
    r = await integration_client.get("/api/v1/skins/karambit-doppler-factory-new-phase-2")
    assert r.status_code == 200
    body = r.json()
    assert body["phase"] == "Phase 2"
    # 1450: 29.35 bracket margin + (3 % + 3 pp for a single listing) × 1450 = 87.00 -> 1566.35
    assert body["cheapest"] == [
        {"listing_id": 1, "price_usd": "1566.35", "price_uzs": _uzs("1566.35")}
    ]
    assert (await integration_client.get("/api/v1/skins/nope")).status_code == 404
