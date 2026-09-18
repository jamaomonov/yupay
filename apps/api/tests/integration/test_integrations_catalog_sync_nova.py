"""End-to-end catalogue sync for NOVA — the games + game_denom half of the
supplier-catalog-pickers feature.

Mirrors ``test_integrations_catalog_sync.py`` (G2B) in shape: real routes,
respx-mocked NOVA responses, assertions against ``supplier_catalog_cache``
through the admin ``GET /catalog`` listing. NOVA has no voucher concept, so
every test here is games/denominations only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
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
from yupay.modules.integrations.models import NOVA_STEAM_SENTINEL, SkuSupplierMapping
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
BASE = "https://nova.catalog.test"


@pytest.fixture(autouse=True)
def _nova_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOVA_API_KEY", "test-key")
    monkeypatch.setenv("NOVA_BASE_URL", BASE)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login_admin(client: AsyncClient, db: AsyncSession, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200
    token = r.json()["access_token"]
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return token


async def _seed_mapped_sku(
    db: AsyncSession, *, slug: str, supplier_slug: str, external_product_id: str
) -> str:
    """A SKU with an active ``game`` mapping to ``external_product_id`` —
    what makes the sync treat that game's denominations as "already mapped"."""
    category = Category(
        id=new_id(),
        slug=f"cat-{slug}",
        sort_order=1,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=slug)],
    )
    brand = Brand(
        id=new_id(),
        category_id=category.id,
        slug=f"brand-{slug}",
        sort_order=1,
        active=True,
        translations=[BrandTranslation(locale="ru", name=slug)],
    )
    product = Product(
        id=new_id(),
        brand_id=brand.id,
        slug=f"product-{slug}",
        kind="top_up",
        sort_order=1,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name=slug)],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"SKU-{slug}",
        denomination="1",
        region="GLOBAL",
        price_usd=Decimal("1.00"),
        sort_order=1,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.commit()
    db.add(
        SkuSupplierMapping(
            sku_id=sku.id,
            supplier_slug=supplier_slug,
            kind="game",
            external_product_id=external_product_id,
            is_active=True,
        )
    )
    await db.commit()
    return sku.id


@respx.mock
async def test_nova_games_sync_writes_game_rows(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    respx.get(f"{BASE}/api/v2/topups", params={"limit": "100"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [
                    {"category_id": "mobile_legends_ru", "name": "Mobile Legends (RU)"},
                    {"category_id": "pubg_mobile_auto", "name": "PUBG Mobile (Auto)"},
                ],
                "meta": {"total": 2, "limit": 100, "next_cursor": None, "has_more": False},
            },
        )
    )

    admin = await _login_admin(integration_client, db_session, tg_id=701)
    headers = {"Authorization": f"Bearer {admin}"}

    sync = await integration_client.post(
        "/api/v1/admin/integrations/nova/sync-catalog", headers=headers
    )
    assert sync.status_code == 200, sync.text
    body = sync.json()
    assert body["supplier"] == "nova"
    assert body["games_synced"] == 2
    assert body["vouchers_synced"] == 0
    assert body["error"] is None

    listing = await integration_client.get(
        "/api/v1/admin/integrations/catalog?supplier_slug=nova&kind=game", headers=headers
    )
    ids = {it["external_id"] for it in listing.json()["items"]}
    assert ids == {"mobile_legends_ru", "pubg_mobile_auto"}


@respx.mock
async def test_sync_writes_denominations_only_for_a_mapped_game(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Two games come back from the sweep; only one is mapped. The unmapped
    game's offers endpoint is never registered with respx — if the sync
    tried to call it anyway, this test would fail on the network call
    itself rather than on an assertion."""
    await _seed_mapped_sku(
        db_session, slug="mlbb", supplier_slug="nova", external_product_id="mobile_legends_ru"
    )

    respx.get(f"{BASE}/api/v2/topups", params={"limit": "100"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [
                    {"category_id": "mobile_legends_ru", "name": "Mobile Legends (RU)"},
                    {"category_id": "pubg_mobile_auto", "name": "PUBG Mobile (Auto)"},
                ],
                "meta": {"total": 2, "limit": 100, "next_cursor": None, "has_more": False},
            },
        )
    )
    offers = respx.get(
        f"{BASE}/api/v2/topups/offers", params={"category_id": "mobile_legends_ru"}
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "category_id": "mobile_legends_ru",
                "offers": [
                    {"offer_id": "275_diamonds", "name": "275 Diamonds", "price_usd": "4.72"}
                ],
            },
        )
    )

    admin = await _login_admin(integration_client, db_session, tg_id=702)
    headers = {"Authorization": f"Bearer {admin}"}
    sync = await integration_client.post(
        "/api/v1/admin/integrations/nova/sync-catalog", headers=headers
    )
    assert sync.status_code == 200, sync.text
    body = sync.json()
    assert body["games_synced"] == 2
    assert body["mapped_vouchers_refreshed"] == 1
    assert offers.called

    listing = await integration_client.get(
        "/api/v1/admin/integrations/catalog"
        "?supplier_slug=nova&kind=game_denom&parent_external_id=mobile_legends_ru",
        headers=headers,
    )
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["external_id"] == "275_diamonds"
    assert Decimal(items[0]["price_usdt"]) == Decimal("4.72")
    assert items[0]["parent_external_id"] == "mobile_legends_ru"

    # The unmapped game has no denominations cached at all.
    other = await integration_client.get(
        "/api/v1/admin/integrations/catalog"
        "?supplier_slug=nova&kind=game_denom&parent_external_id=pubg_mobile_auto",
        headers=headers,
    )
    assert other.json()["items"] == []


@respx.mock
async def test_on_demand_denomination_sync_for_an_unmapped_game(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The operator picked a game the cache has never seen — the explicit
    per-game endpoint, not the hourly sweep, is what fills it in."""
    route = respx.get(
        f"{BASE}/api/v2/topups/offers", params={"category_id": "genshin_impact"}
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "category_id": "genshin_impact",
                "offers": [
                    {"offer_id": "60_crystals", "name": "60 Genesis Crystals", "price_usd": "0.9"},
                    {
                        "offer_id": "300_crystals",
                        "name": "300 Genesis Crystals",
                        "price_usd": "4.5",
                    },
                ],
            },
        )
    )

    admin = await _login_admin(integration_client, db_session, tg_id=703)
    headers = {"Authorization": f"Bearer {admin}", "Idempotency-Key": "nova-denom-sync-key-001"}
    resp = await integration_client.post(
        "/api/v1/admin/integrations/nova/games/genshin_impact/sync-denominations",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "supplier": "nova",
        "game_id": "genshin_impact",
        "denominations_synced": 2,
        "error": None,
    }
    assert route.called

    listing = await integration_client.get(
        "/api/v1/admin/integrations/catalog"
        "?supplier_slug=nova&kind=game_denom&parent_external_id=genshin_impact",
        headers=headers,
    )
    assert {it["external_id"] for it in listing.json()["items"]} == {
        "60_crystals",
        "300_crystals",
    }


@respx.mock
async def test_on_demand_sync_of_an_unknown_category_reports_not_crashes(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    respx.get(f"{BASE}/api/v2/topups/offers", params={"category_id": "no_such_game"}).mock(
        return_value=httpx.Response(404, json={"ok": False, "error": "not found"})
    )

    admin = await _login_admin(integration_client, db_session, tg_id=704)
    headers = {"Authorization": f"Bearer {admin}", "Idempotency-Key": "nova-denom-sync-key-002"}
    resp = await integration_client.post(
        "/api/v1/admin/integrations/nova/games/no_such_game/sync-denominations",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["denominations_synced"] == 0
    assert body["error"]


@respx.mock
async def test_the_old_g2b_only_supplier_value_still_works_generically(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """``supplier`` is now a path parameter accepting g2b|nova|gengine; an
    unsupported value is refused with a clean 422, not a 404 or a 500."""
    admin = await _login_admin(integration_client, db_session, tg_id=705)
    headers = {"Authorization": f"Bearer {admin}"}
    resp = await integration_client.post(
        "/api/v1/admin/integrations/waxpeer/sync-catalog", headers=headers
    )
    assert resp.status_code == 422


@respx.mock
async def test_steam_sentinel_mapping_causes_no_call_and_no_missing_upstream(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The Steam reserve mapping's ``external_product_id`` is the sentinel
    ``"steam-topup"`` — it has no catalogue offers to fetch (ADR-0082 §4),
    the same fact ``price_refresh._fetch_nova_offers_cache`` and
    ``cost_lookup._nova_raw_price`` already special-case. If the
    mapped-denom refresh tried to call ``get_offers("steam-topup")``
    anyway, this test would fail on the unmocked network call itself — no
    respx route is registered for it — rather than on an assertion, the
    same technique ``test_sync_writes_denominations_only_for_a_mapped_game``
    uses for an unmapped game above."""
    await _seed_mapped_sku(
        db_session,
        slug="steam",
        supplier_slug="nova",
        external_product_id=NOVA_STEAM_SENTINEL,
    )

    respx.get(f"{BASE}/api/v2/topups", params={"limit": "100"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [{"category_id": "mobile_legends_ru", "name": "Mobile Legends (RU)"}],
                "meta": {"total": 1, "limit": 100, "next_cursor": None, "has_more": False},
            },
        )
    )

    admin = await _login_admin(integration_client, db_session, tg_id=706)
    headers = {"Authorization": f"Bearer {admin}"}
    sync = await integration_client.post(
        "/api/v1/admin/integrations/nova/sync-catalog", headers=headers
    )
    assert sync.status_code == 200, sync.text
    body = sync.json()
    assert body["games_synced"] == 1
    assert body["mapped_vouchers_refreshed"] == 0
    assert body["missing_upstream"] == 0
    assert body["error"] is None


@respx.mock
async def test_malformed_offer_payload_is_reported_not_raised(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A non-dict entry in ``offers`` used to raise an uncaught
    ``AttributeError`` straight out of the best-effort sync — ``list_topups``
    filters its own items to dicts, but the per-category offers loop did
    not. It must report as ``error`` on a 200 instead of a 5xx."""
    await _seed_mapped_sku(
        db_session, slug="mlbb2", supplier_slug="nova", external_product_id="mobile_legends_ru"
    )
    respx.get(f"{BASE}/api/v2/topups", params={"limit": "100"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [{"category_id": "mobile_legends_ru", "name": "Mobile Legends (RU)"}],
                "meta": {"total": 1, "limit": 100, "next_cursor": None, "has_more": False},
            },
        )
    )
    respx.get(f"{BASE}/api/v2/topups/offers", params={"category_id": "mobile_legends_ru"}).mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "category_id": "mobile_legends_ru", "offers": ["not-a-dict"]},
        )
    )

    admin = await _login_admin(integration_client, db_session, tg_id=707)
    headers = {"Authorization": f"Bearer {admin}"}
    sync = await integration_client.post(
        "/api/v1/admin/integrations/nova/sync-catalog", headers=headers
    )
    assert sync.status_code == 200, sync.text
    body = sync.json()
    assert body["mapped_vouchers_refreshed"] == 0
    assert body["error"]
    assert "1 mapped game(s) failed to refresh offers" in body["error"]
