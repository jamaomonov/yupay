"""End-to-end catalogue sync for G-Engine — games (recharge services) +
game_denom, the two-level picker the mapping wizard needs to stop asking
operators to type a ``service_id``/``denomination_id`` by hand.

G-Engine's ``GET /recharge/services`` returns each service's denominations
inline, so — unlike NOVA — the mapped-game denomination refresh here costs no
extra HTTP call; see ``catalog_sync_gengine.py``'s module docstring.
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
import structlog.testing
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
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
BASE = "https://gengine.catalog.test/v2.1"


@pytest.fixture(autouse=True)
def _gengine_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GENGINE_API_KEY", "test-key")
    monkeypatch.setenv("GENGINE_BASE_URL", BASE)
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


async def _seed_mapped_sku(db: AsyncSession, *, slug: str, external_product_id: str) -> str:
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
            supplier_slug="gengine",
            kind="game",
            external_product_id=external_product_id,
            is_active=True,
        )
    )
    await db.commit()
    return sku.id


_SERVICES_PAGE = {
    "total": 2,
    "limit": 100,
    "offset": 0,
    "items": [
        {
            "id": 5,
            "name": "Mobile Legends Bang Bang (Russia)",
            "type": "fixed",
            "params": [{"param_key": "Account", "param_type": "String"}],
            "denominations": [
                {"id": 1, "name": "32 + 3 Diamonds", "value": "35", "price": 0.6018},
                {"id": 2, "name": "86 Diamonds", "value": "86", "price": 1.42},
            ],
        },
        {
            "id": 9,
            "name": "PUBG Mobile",
            "type": "fixed",
            "params": [{"param_key": "Account", "param_type": "String"}],
            "denominations": [{"id": 3, "name": "60 UC", "value": "60", "price": 0.9}],
        },
    ],
}


@respx.mock
async def test_gengine_games_sync_writes_game_rows(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    respx.get(f"{BASE}/recharge/services").mock(
        return_value=httpx.Response(200, json=_SERVICES_PAGE)
    )

    admin = await _login_admin(integration_client, db_session, tg_id=801)
    headers = {"Authorization": f"Bearer {admin}"}
    sync = await integration_client.post(
        "/api/v1/admin/integrations/gengine/sync-catalog", headers=headers
    )
    assert sync.status_code == 200, sync.text
    body = sync.json()
    assert body["supplier"] == "gengine"
    assert body["games_synced"] == 2
    assert body["vouchers_synced"] == 0
    assert body["error"] is None

    listing = await integration_client.get(
        "/api/v1/admin/integrations/catalog?supplier_slug=gengine&kind=game", headers=headers
    )
    ids = {it["external_id"] for it in listing.json()["items"]}
    assert ids == {"5", "9"}


@respx.mock
async def test_sync_writes_denominations_only_for_a_mapped_service_no_extra_call(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Denominations arrive inline with the services list — this asserts
    exactly one HTTP call happens (the services page), and only the mapped
    service's denominations land in the cache."""
    await _seed_mapped_sku(db_session, slug="mlbb", external_product_id="5")

    route = respx.get(f"{BASE}/recharge/services").mock(
        return_value=httpx.Response(200, json=_SERVICES_PAGE)
    )

    admin = await _login_admin(integration_client, db_session, tg_id=802)
    headers = {"Authorization": f"Bearer {admin}"}
    sync = await integration_client.post(
        "/api/v1/admin/integrations/gengine/sync-catalog", headers=headers
    )
    assert sync.status_code == 200, sync.text
    body = sync.json()
    assert body["games_synced"] == 2
    assert body["mapped_vouchers_refreshed"] == 2  # 2 denominations under service 5
    assert route.call_count == 1, "denominations are already inline — no extra call is needed"

    mapped = await integration_client.get(
        "/api/v1/admin/integrations/catalog?supplier_slug=gengine&kind=game_denom&parent_external_id=5",
        headers=headers,
    )
    items = mapped.json()["items"]
    assert {it["external_id"] for it in items} == {"1", "2"}
    priced = next(it for it in items if it["external_id"] == "1")
    assert Decimal(priced["price_usdt"]) == Decimal("0.6018")

    unmapped = await integration_client.get(
        "/api/v1/admin/integrations/catalog?supplier_slug=gengine&kind=game_denom&parent_external_id=9",
        headers=headers,
    )
    assert unmapped.json()["items"] == []


@respx.mock
async def test_on_demand_denomination_sync_for_an_unmapped_service(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    respx.get(f"{BASE}/recharge/services").mock(
        return_value=httpx.Response(200, json=_SERVICES_PAGE)
    )

    admin = await _login_admin(integration_client, db_session, tg_id=803)
    headers = {"Authorization": f"Bearer {admin}", "Idempotency-Key": "gengine-denom-sync-key-1"}
    resp = await integration_client.post(
        "/api/v1/admin/integrations/gengine/games/9/sync-denominations", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "supplier": "gengine",
        "game_id": "9",
        "denominations_synced": 1,
        "error": None,
    }

    listing = await integration_client.get(
        "/api/v1/admin/integrations/catalog?supplier_slug=gengine&kind=game_denom&parent_external_id=9",
        headers=headers,
    )
    assert [it["external_id"] for it in listing.json()["items"]] == ["3"]


@respx.mock
async def test_on_demand_sync_of_an_unknown_service_reports_not_crashes(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    respx.get(f"{BASE}/recharge/services").mock(
        return_value=httpx.Response(200, json=_SERVICES_PAGE)
    )

    admin = await _login_admin(integration_client, db_session, tg_id=804)
    headers = {"Authorization": f"Bearer {admin}", "Idempotency-Key": "gengine-denom-sync-key-2"}
    resp = await integration_client.post(
        "/api/v1/admin/integrations/gengine/games/999/sync-denominations", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["denominations_synced"] == 0
    assert body["error"]


@respx.mock
async def test_on_demand_sync_reports_a_malformed_denomination_not_raises(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """``_write_denoms`` used to run outside ``sync_gengine_game_denominations``'s
    ``try`` — a junk price ``Decimal(str(...))`` can't parse would raise
    ``decimal.InvalidOperation`` straight out of the route. It must report
    as ``error`` on a 200 instead."""
    respx.get(f"{BASE}/recharge/services").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "limit": 100,
                "offset": 0,
                "items": [
                    {
                        "id": 42,
                        "name": "Broken Service",
                        "type": "fixed",
                        "params": [],
                        "denominations": [
                            {"id": 1, "name": "Junk Price", "value": "1", "price": "not-a-number"}
                        ],
                    }
                ],
            },
        )
    )

    admin = await _login_admin(integration_client, db_session, tg_id=806)
    headers = {"Authorization": f"Bearer {admin}", "Idempotency-Key": "gengine-denom-sync-key-3"}
    resp = await integration_client.post(
        "/api/v1/admin/integrations/gengine/games/42/sync-denominations", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["denominations_synced"] == 0
    assert body["error"]


@respx.mock
async def test_two_page_ceiling_warns_and_suppresses_missing_upstream(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Page one and page two both come back at the 100-item cap — a third
    page almost certainly exists and was never fetched. A mapped service
    that lives only on that unfetched tail must not read as "gone
    upstream" (``missing_upstream`` stays 0 for this tick), and the
    truncation is logged so an operator can go looking rather than trust a
    false "everything's fine"."""
    await _seed_mapped_sku(db_session, slug="ghost", external_product_id="999")

    # ids start at 1 — ``sync_gengine_catalog`` treats a falsy ``id`` (``0``
    # included, since ``item.get("id") or ""`` is falsy for ``0``) as
    # unusable and skips it, which would make this test's own count wrong
    # rather than exercising the truncation it's here to check.
    page_one = {
        "total": 250,
        "limit": 100,
        "offset": 0,
        "items": [
            {"id": i, "name": f"Service {i}", "type": "fixed", "params": [], "denominations": []}
            for i in range(1, 101)
        ],
    }
    page_two = {
        "total": 250,
        "limit": 100,
        "offset": 100,
        "items": [
            {"id": i, "name": f"Service {i}", "type": "fixed", "params": [], "denominations": []}
            for i in range(101, 201)
        ],
    }
    respx.get(f"{BASE}/recharge/services", params={"limit": "100", "offset": "0"}).mock(
        return_value=httpx.Response(200, json=page_one)
    )
    respx.get(f"{BASE}/recharge/services", params={"limit": "100", "offset": "100"}).mock(
        return_value=httpx.Response(200, json=page_two)
    )

    admin = await _login_admin(integration_client, db_session, tg_id=805)
    headers = {"Authorization": f"Bearer {admin}"}
    with structlog.testing.capture_logs() as captured:
        sync = await integration_client.post(
            "/api/v1/admin/integrations/gengine/sync-catalog", headers=headers
        )
    assert sync.status_code == 200, sync.text
    body = sync.json()
    assert body["games_synced"] == 200
    assert body["missing_upstream"] == 0, "mapped id 999 fell off page two, not gone upstream"
    assert any(
        entry.get("event") == "integrations.gengine.sync.services_page_limit_hit"
        for entry in captured
    )
