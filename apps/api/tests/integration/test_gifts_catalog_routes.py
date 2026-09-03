"""HTTP tests for the public gifts catalog routes (`GET /api/v1/gifts/*`).

Covers:
- the `steam_gifts_enabled` router guard: every route 404s while it's off;
- listing maps upstream fields and applies the admin margin;
- detail narrows package prices to the offered zones only;
- `/dlc` filters and paginates the cached detail's `dlc[]` server-side,
  never the flat catalog listing;
- a G-Engine outage falls back to the warm stale cache instead of 502ing.

FX is sidestepped via a manual USD->UZS override written straight to Redis
(`FxService.publish_quote_setting`) rather than an admin HTTP round trip —
`_manual_quote` short-circuits `FxService.get_rate` before it would ever
reach a live provider, which `@respx.mock` would otherwise refuse to let
through unmocked.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx
import pytest
import respx
from httpx import AsyncClient
from yupay.core import config as cfg
from yupay.core.redis import get_redis
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.quote_settings import ManualOverride

pytestmark = pytest.mark.asyncio

BASE = "https://gengine.gifts.test/v2.1"
API_KEY = "gengine-gifts-test-key"
_UZS_RATE = Decimal("12700")


@pytest.fixture(autouse=True)
def _gengine_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GENGINE_API_KEY", API_KEY)
    monkeypatch.setenv("GENGINE_BASE_URL", BASE)
    monkeypatch.setenv("STEAM_GIFTS_MARGIN_PERCENT", "10")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def _uzs_manual_rate(integration_client: AsyncClient) -> None:
    """Every enabled-route test needs FX to resolve without a live provider
    call — a manual override answers ``fx.convert`` straight out of Redis,
    regardless of whether ``@respx.mock`` is active for a given test."""
    fx = build_default_service()
    override = ManualOverride(quote="UZS", use_manual=True, manual_rate=_UZS_RATE, updated_at=None)
    await fx.publish_quote_setting(override)


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STEAM_GIFTS_ENABLED", "true")
    cfg.get_settings.cache_clear()


def _expected_uzs(usd: str) -> str:
    return str((Decimal(usd) * _UZS_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def _seed_list_stale(
    *, offset: int, limit: int, items: list[dict[str, Any]], total: int
) -> None:
    redis = get_redis()
    payload = json.dumps({"items": items, "total": total})
    await redis.set(f"gifts:list:{offset}:{limit}:stale", payload)


# ---------- the enabled guard ----------


async def test_disabled_flag_404s_every_route(integration_client: AsyncClient) -> None:
    """`steam_gifts_enabled` defaults to False; nothing under `/gifts` should
    answer with anything but 404 — not even a real error for a bad app id."""
    paths = [
        "/api/v1/gifts/catalog",
        "/api/v1/gifts/catalog/hot",
        "/api/v1/gifts/catalog/588650",
        "/api/v1/gifts/catalog/588650/dlc",
    ]
    for path in paths:
        r = await integration_client.get(path)
        assert r.status_code == 404, (path, r.text)


# ---------- listing ----------


@respx.mock
async def test_enabled_listing_maps_fields_and_applies_margin(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    respx.get(f"{BASE}/gifts/apps").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "items": [
                    {
                        "id": 588650,
                        "name": "Dead Cells",
                        "type": "game",
                        "image": "https://cdn.example/dead-cells.jpg",
                        "price": 0.97,
                        "discount_percent": 20,
                        "package_ids": [1, 2],
                        "dlc_ids": [9001],
                    }
                ],
            },
        )
    )

    r = await integration_client.get("/api/v1/gifts/catalog")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["app_id"] == 588650
    assert item["name"] == "Dead Cells"
    assert item["image"] == "https://cdn.example/dead-cells.jpg"
    assert item["type"] == "game"
    # 0.97 * 1.10 = 1.067 -> HALF_UP to 2dp = 1.07
    assert item["price_usd"] == "1.07"
    assert item["price_uzs"] == _expected_uzs("1.07")
    assert item["discount_percent"] == 20
    assert item["packages_count"] == 2
    assert item["dlc_count"] == 1


@respx.mock
async def test_listing_row_with_no_reference_price_shows_no_price(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    respx.get(f"{BASE}/gifts/apps").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "items": [
                    {
                        "id": 1,
                        "name": "No Price Game",
                        "type": "game",
                        "image": None,
                        "price": None,
                        "discount_percent": None,
                        "package_ids": [],
                        "dlc_ids": [],
                    }
                ],
            },
        )
    )

    r = await integration_client.get("/api/v1/gifts/catalog")

    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["price_usd"] is None
    assert item["price_uzs"] is None


@pytest.mark.parametrize(
    "query",
    ["limit=1000", "limit=0", "offset=-1"],
)
async def test_catalog_limit_and_offset_are_bounded(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    """``limit``/``offset`` are ``Query(..., ge=1, le=100)`` /
    ``Query(..., ge=0)`` (mirrors reviews/routes.py:82) — every distinct
    pair otherwise mints its own ``gifts:list``/``gifts:search`` Redis key
    plus a 24h stale twin and one upstream call, unbounded. No G-Engine
    mock is needed: parameter validation rejects the request before the
    route body — and therefore any upstream call — ever runs."""
    _enable(monkeypatch)

    r = await integration_client.get(f"/api/v1/gifts/catalog?{query}")

    assert r.status_code == 422, r.text


# ---------- detail ----------


@respx.mock
async def test_detail_exposes_only_offered_zones(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    respx.get(f"{BASE}/gifts/apps/588650").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 588650,
                "name": "Dead Cells",
                "type": "game",
                "image": "cover.jpg",
                "price": 0.97,
                "discount_percent": 0,
                "description": "A rogue-lite, Metroidvania-inspired action-platformer.",
                "dlc": [
                    {
                        "id": 9001,
                        "name": "Dead Cells: The Bad Seed",
                        "type": "dlc",
                        "image": None,
                        "price": 2.99,
                        "discount_percent": None,
                        "package_ids": [],
                        "dlc_ids": [],
                    }
                ],
                "packages": [
                    {
                        "id": 1,
                        "name": "Standard Edition",
                        "image": "pkg1.jpg",
                        "discount_percent": 0,
                        "prices": [
                            {"region": "CIS", "currency": "USD", "price": 1.02, "zone": "CIS"},
                            {"region": "Russia", "currency": "RUB", "price": 0.85, "zone": "RU"},
                            # Not in the offered zone list — must never surface.
                            {"region": "Other", "currency": "USD", "price": 5.0, "zone": "XX"},
                        ],
                    },
                    {
                        "id": 2,
                        "name": "Deluxe Edition",
                        "image": "pkg2.jpg",
                        "discount_percent": 10,
                        "prices": [
                            # Offered, but the upstream price itself is null.
                            {
                                "region": "Kazakhstan",
                                "currency": "KZT",
                                "price": None,
                                "zone": "KZ",
                            },
                        ],
                    },
                ],
            },
        )
    )

    r = await integration_client.get("/api/v1/gifts/catalog/588650")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["app_id"] == 588650
    assert body["description"].startswith("A rogue-lite")
    assert body["dlc_total"] == 1
    assert body["dlc_count"] == 1
    assert body["packages_count"] == 2
    # Deprecated zone twin — kept one release for a stale client, whose
    # `prices.find(p => p.zone === zone_default)` needs an actual zone, not
    # the country `region_default` resolves to (2026-09-03: the default
    # became a country, "UZ"; `zone_default` resolves it back to the zone
    # that covers it, "CIS").
    assert body["zone_default"] == "CIS"
    # KZ only had a null price and XX isn't in STEAM_GIFTS_REGIONS at all —
    # neither shows up, regardless of appearing in the raw upstream payload.
    assert body["zones"] == ["CIS", "RU"]

    pkg1 = next(p for p in body["packages"] if p["id"] == 1)
    prices_by_zone = {p["zone"]: p for p in pkg1["prices"]}
    assert set(prices_by_zone) == {"CIS", "RU"}
    # 1.02 * 1.10 = 1.122 -> HALF_UP to 2dp = 1.12
    assert prices_by_zone["CIS"]["price_usd"] == "1.12"
    assert prices_by_zone["CIS"]["price_uzs"] == _expected_uzs("1.12")

    pkg2 = next(p for p in body["packages"] if p["id"] == 2)
    assert pkg2["prices"] == []

    # ---- regions: the country picker ----
    assert body["region_default"] == "UZ"
    region_countries = [r["country"] for r in body["regions"]]
    assert region_countries[0] == "UZ"
    # Every CIS country appears (this fixture's offered zones are the code
    # default CIS/RU/KZ/UA), none from outside the offered zones.
    cis_countries = {"UZ", "GE", "KG", "MD", "TJ", "TM", "AM", "AZ", "BY"}
    assert cis_countries <= set(region_countries)
    assert set(region_countries) & {"KZ", "UA"} == set()  # KZ null-priced, UA not offered here
    assert set(region_countries) - cis_countries == {"RU"}

    regions_by_country = {r["country"]: r for r in body["regions"]}
    for country in cis_countries:
        assert regions_by_country[country]["zone"] == "CIS"
        # Every CIS country shows the identical CIS price.
        assert regions_by_country[country]["price_usd"] == "1.12"
        assert regions_by_country[country]["price_uzs"] == _expected_uzs("1.12")
    assert regions_by_country["RU"]["zone"] == "RU"
    # 0.85 * 1.10 = 0.935 -> HALF_UP to 2dp = 0.94
    assert regions_by_country["RU"]["price_usd"] == "0.94"


@respx.mock
async def test_detail_resolves_a_legacy_zone_label_default_to_a_priced_country(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``STEAM_GIFTS_REGION_DEFAULT`` can still be set to a legacy zone label
    (e.g. an unreloaded dev/staging env carrying the pre-2026-09-03
    ``CIS`` default — see ``docker-compose.yml``). ``zone_for_country("CIS",
    ...)`` resolves to ``None`` (a zone key is never itself a member of any
    ``ZONE_COUNTRIES`` tuple), so ``region_default`` must never come back as
    that raw, unresolved value — both frontends require it to be a member of
    ``regions[].country``, or they start with no priced selection and a
    disabled Buy button on first paint."""
    monkeypatch.setenv("STEAM_GIFTS_ENABLED", "true")
    monkeypatch.setenv("STEAM_GIFTS_REGION_DEFAULT", "CIS")
    cfg.get_settings.cache_clear()
    respx.get(f"{BASE}/gifts/apps/730").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 730,
                "name": "Counter-Strike 2",
                "type": "game",
                "image": "cover.jpg",
                "price": 1.0,
                "discount_percent": 0,
                "description": None,
                "dlc": [],
                "packages": [
                    {
                        "id": 1,
                        "name": "Standard Edition",
                        "image": None,
                        "discount_percent": 0,
                        "prices": [
                            {"region": "CIS", "currency": "USD", "price": 1.0, "zone": "CIS"},
                            {"region": "Russia", "currency": "RUB", "price": 0.9, "zone": "RU"},
                        ],
                    },
                ],
            },
        )
    )

    r = await integration_client.get("/api/v1/gifts/catalog/730")

    assert r.status_code == 200, r.text
    body = r.json()
    region_countries = [reg["country"] for reg in body["regions"]]
    # Never the raw configured zone label — it must resolve to a real,
    # priced country.
    assert body["region_default"] != "CIS"
    assert body["region_default"] in region_countries
    # UZ leads the CIS zone's country list (see ZONE_COUNTRIES' comment),
    # and CIS is first in STEAM_GIFTS_REGIONS' default order — so once the
    # configured "CIS" fails to match any country, the fallback to the
    # first available region lands on UZ.
    assert body["region_default"] == "UZ"
    # The deprecated zone twin must also always be a member of the
    # deprecated zone list — never the raw configured value verbatim.
    assert body["zone_default"] in body["zones"]
    assert body["zone_default"] == "CIS"


@respx.mock
async def test_unknown_app_id_is_404(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    respx.get(f"{BASE}/gifts/apps/999999").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )

    r = await integration_client.get("/api/v1/gifts/catalog/999999")

    assert r.status_code == 404, r.text


# ---------- dlc ----------


_DEAD_CELLS_DETAIL_WITH_DLC: dict[str, Any] = {
    "id": 588650,
    "name": "Dead Cells",
    "type": "game",
    "image": "cover.jpg",
    "price": 0.97,
    "discount_percent": 0,
    "description": "A rogue-lite.",
    "packages": [],
    "dlc": [
        {
            "id": 9001,
            "name": "Dead Cells: The Bad Seed",
            "type": "dlc",
            "image": None,
            "price": 2.99,
            "discount_percent": None,
            "package_ids": [],
            "dlc_ids": [],
        },
        {
            "id": 9002,
            "name": "Dead Cells: Fatal Falls",
            "type": "dlc",
            "image": None,
            "price": 4.99,
            "discount_percent": 10,
            "package_ids": [],
            "dlc_ids": [],
        },
        {
            "id": 9003,
            "name": "Dead Cells: The Queen and the Sea",
            "type": "dlc",
            "image": None,
            "price": 3.99,
            "discount_percent": None,
            "package_ids": [],
            "dlc_ids": [],
        },
    ],
}


@respx.mock
async def test_dlc_filters_by_search_server_side(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    # The flat listing endpoint is intentionally never mocked: if the /dlc
    # route ever fell back to it, respx would refuse the unmocked call.
    respx.get(f"{BASE}/gifts/apps/588650").mock(
        return_value=httpx.Response(200, json=_DEAD_CELLS_DETAIL_WITH_DLC)
    )

    unfiltered = await integration_client.get("/api/v1/gifts/catalog/588650/dlc")
    assert unfiltered.status_code == 200, unfiltered.text
    assert unfiltered.json()["total"] == 3

    filtered = await integration_client.get("/api/v1/gifts/catalog/588650/dlc?search=bad")
    assert filtered.status_code == 200, filtered.text
    filtered_body = filtered.json()
    assert filtered_body["total"] == 1
    assert filtered_body["items"][0]["app_id"] == 9001
    assert filtered_body["items"][0]["name"] == "Dead Cells: The Bad Seed"


@respx.mock
async def test_dlc_pages_server_side(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    respx.get(f"{BASE}/gifts/apps/588650").mock(
        return_value=httpx.Response(200, json=_DEAD_CELLS_DETAIL_WITH_DLC)
    )

    r = await integration_client.get("/api/v1/gifts/catalog/588650/dlc?limit=1&offset=1")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert [i["app_id"] for i in body["items"]] == [9002]


# ---------- stale-while-error ----------


@respx.mock
async def test_upstream_down_serves_warm_stale_listing(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    stale_items = [
        {
            "id": 42,
            "name": "Stale Game",
            "type": "game",
            "image": None,
            "price": 2.00,
            "discount_percent": 0,
            "package_ids": [],
            "dlc_ids": [],
        }
    ]
    await _seed_list_stale(offset=0, limit=24, items=stale_items, total=1)
    respx.get(f"{BASE}/gifts/apps").mock(side_effect=httpx.ConnectError("g-engine is down"))

    r = await integration_client.get("/api/v1/gifts/catalog")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["app_id"] == 42
    assert body["items"][0]["name"] == "Stale Game"


@respx.mock
async def test_upstream_down_with_no_stale_is_502(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    respx.get(f"{BASE}/gifts/apps").mock(side_effect=httpx.ConnectError("g-engine is down"))

    r = await integration_client.get("/api/v1/gifts/catalog")

    assert r.status_code == 502, r.text
