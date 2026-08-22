"""End-to-end sync-catalog flow with respx-mocked G2B responses.

Lives in its own file because it needs the same ``_g2b_env`` autouse
fixture as the fulfilment e2e tests — those set ``G2B_API_KEY=test-key``
and ``G2B_BASE_URL=https://g2b.test/v1`` which lets the adapter actually
make HTTP calls (intercepted by respx) instead of short-circuiting on
``available=False``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
G2B_BASE = "https://g2b.test/v1"


@pytest.fixture(autouse=True)
def _g2b_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("G2B_API_KEY", "test-key")
    monkeypatch.setenv("G2B_BASE_URL", G2B_BASE)
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


@respx.mock
async def test_sync_populates_catalog_cache(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    # Real G2B shape: ``{"products": [...]}`` and ``{"games": [...]}``.
    respx.get(f"{G2B_BASE}/products?page=1&limit=200").mock(
        return_value=httpx.Response(
            200,
            json={
                "products": [
                    {"id": 1, "title": "PUBG UC Voucher", "unit_price": 1.5},
                    {"id": 2, "title": "MLBB Diamonds Voucher", "unit_price": 2.5},
                ]
            },
        )
    )
    respx.get(f"{G2B_BASE}/games").mock(
        return_value=httpx.Response(
            200,
            json={
                "games": [
                    {"code": "pubg_mobile", "name": "PUBG Mobile"},
                    {"code": "mlbb", "name": "Mobile Legends"},
                ]
            },
        )
    )

    admin = await _login_admin(integration_client, db_session, tg_id=601)
    headers = {"Authorization": f"Bearer {admin}"}

    sync = await integration_client.post(
        "/api/v1/admin/integrations/g2b/sync-catalog",
        headers=headers,
    )
    assert sync.status_code == 200
    body = sync.json()
    assert body["vouchers_synced"] == 2
    assert body["games_synced"] == 2
    assert body["error"] is None

    listing = await integration_client.get(
        "/api/v1/admin/integrations/catalog?supplier_slug=g2b",
        headers=headers,
    )
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 4
    voucher_titles = {it["title"] for it in items if it["kind"] == "voucher"}
    assert "PUBG UC Voucher" in voucher_titles
    game_codes = {it["external_id"] for it in items if it["kind"] == "game"}
    assert "pubg_mobile" in game_codes


@respx.mock
async def test_sync_continues_when_one_endpoint_fails(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Voucher fetch fails, games still get cached. Sync reports the
    partial failure but doesn't 500."""
    respx.get(f"{G2B_BASE}/products?page=1&limit=200").mock(
        return_value=httpx.Response(500, text="boom")
    )
    respx.get(f"{G2B_BASE}/games").mock(
        return_value=httpx.Response(200, json={"games": [{"code": "ff", "name": "Free Fire"}]})
    )

    admin = await _login_admin(integration_client, db_session, tg_id=602)
    sync = await integration_client.post(
        "/api/v1/admin/integrations/g2b/sync-catalog",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert sync.status_code == 200
    body = sync.json()
    assert body["vouchers_synced"] == 0
    assert body["games_synced"] == 1
    assert body["error"]


@respx.mock
async def test_a_mapped_voucher_is_refreshed_even_when_it_is_not_on_page_one(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The sweep reads page one of a catalogue ~12 800 rows deep.

    Whether a product we actually sell got refreshed came down to where it
    happened to sort — which is how a mapped voucher's cost sat twelve days
    stale while the hourly re-price reported `moved: 0`. Mapped products are
    now fetched by id, so the page is irrelevant to them.
    """
    from decimal import Decimal

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
    from yupay.modules.integrations.models import SkuSupplierMapping, SupplierCatalogCache

    category = Category(
        id=new_id(),
        slug="sync-cat",
        sort_order=1,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Sync")],
    )
    brand = Brand(
        id=new_id(),
        category_id=category.id,
        slug="sync-brand",
        sort_order=1,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Sync Brand")],
    )
    product = Product(
        id=new_id(),
        brand_id=brand.id,
        slug="sync-prod",
        kind="voucher",
        sort_order=1,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Sync Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="SYNC-1",
        denomination="1000",
        region="GLOBAL",
        price_usd=Decimal("15.00"),
        sort_order=1,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    db_session.add(
        SkuSupplierMapping(
            sku_id=sku.id,
            supplier_slug="g2b",
            kind="voucher",
            external_product_id="9999",
            is_active=True,
        )
    )
    await db_session.commit()

    # Page one does not contain 9999 — the mapped product sits deeper in.
    respx.get(f"{G2B_BASE}/products?page=1&limit=200").mock(
        return_value=httpx.Response(
            200, json={"products": [{"id": 1, "title": "Something Else", "unit_price": 1.5}]}
        )
    )
    respx.get(f"{G2B_BASE}/games").mock(return_value=httpx.Response(200, json={"games": []}))
    by_id = respx.get(f"{G2B_BASE}/products/9999").mock(
        return_value=httpx.Response(
            200, json={"id": 9999, "title": "Mapped Voucher", "unit_price": 11.25}
        )
    )

    admin = await _login_admin(integration_client, db_session, tg_id=603)
    sync = await integration_client.post(
        "/api/v1/admin/integrations/g2b/sync-catalog",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert sync.status_code == 200, sync.text
    body = sync.json()
    assert body["mapped_vouchers_refreshed"] == 1
    assert body["missing_upstream"] == 0
    assert by_id.called, "the mapped product must be fetched by id, not hoped for on page one"

    cached = (
        await db_session.execute(
            select(SupplierCatalogCache).where(
                SupplierCatalogCache.supplier_slug == "g2b",
                SupplierCatalogCache.kind == "voucher",
                SupplierCatalogCache.external_id == "9999",
            )
        )
    ).scalar_one()
    assert cached.raw["unit_price"] == 11.25


@respx.mock
async def test_a_withdrawn_mapped_voucher_is_counted_not_silently_dropped(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A 404 upstream keeps the last known price and says so."""
    from decimal import Decimal

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

    category = Category(
        id=new_id(),
        slug="gone-cat",
        sort_order=1,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Gone")],
    )
    brand = Brand(
        id=new_id(),
        category_id=category.id,
        slug="gone-brand",
        sort_order=1,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Gone Brand")],
    )
    product = Product(
        id=new_id(),
        brand_id=brand.id,
        slug="gone-prod",
        kind="voucher",
        sort_order=1,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Gone Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="GONE-1",
        denomination="500",
        region="GLOBAL",
        price_usd=Decimal("9.00"),
        sort_order=1,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    db_session.add(
        SkuSupplierMapping(
            sku_id=sku.id,
            supplier_slug="g2b",
            kind="voucher",
            external_product_id="8888",
            is_active=True,
        )
    )
    await db_session.commit()

    respx.get(f"{G2B_BASE}/products?page=1&limit=200").mock(
        return_value=httpx.Response(200, json={"products": []})
    )
    respx.get(f"{G2B_BASE}/games").mock(return_value=httpx.Response(200, json={"games": []}))
    respx.get(f"{G2B_BASE}/products/8888").mock(return_value=httpx.Response(404, text="gone"))

    admin = await _login_admin(integration_client, db_session, tg_id=604)
    sync = await integration_client.post(
        "/api/v1/admin/integrations/g2b/sync-catalog",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert sync.status_code == 200, sync.text
    body = sync.json()
    assert body["mapped_vouchers_refreshed"] == 0
    assert body["missing_upstream"] == 1
    assert body["error"] is None, "a withdrawn product is news, not a failure"
