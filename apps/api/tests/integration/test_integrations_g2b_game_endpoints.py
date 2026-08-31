"""Backend tests for the G2B game helper endpoints used by the mapping UX.

Covers:
- ``GET /admin/integrations/g2b/games/{code}/catalogue`` (denominations)
- ``GET /admin/integrations/g2b/games/{code}/fields`` (required fields)
- ``POST /admin/integrations/g2b/games/{code}/check-player`` (player id proxy)
- ``GET /admin/catalog/skus/search`` (SKU combobox source)

The G2B endpoints all use the same ``_g2b_env`` autouse fixture that
the e2e tests rely on so the adapter actually makes HTTP calls
(intercepted by respx).
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


# ---------- catalogue ----------


@respx.mock
async def test_game_catalogue_returns_denominations(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    # Real G2B shape — ``catalogues`` (plural) with ``amount`` as the
    # upstream USD price (NOT a quantity).
    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={
                "catalogues": [
                    {"id": 264, "name": "60", "amount": 0.89},
                    {"id": 258, "name": "660", "amount": 8.85},
                ],
                "game": {"code": "pubgm", "name": "PUBG Mobile"},
                "success": True,
            },
        )
    )
    admin = await _login_admin(integration_client, db_session, tg_id=701)
    r = await integration_client.get(
        "/api/v1/admin/integrations/g2b/games/pubgm/catalogue",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 2
    assert items[0]["catalogue_name"] == "60"
    # ``price`` falls back to ``amount`` since G2B doesn't ship a separate
    # ``price`` field on the catalogue entries.
    assert items[0]["price"] == "0.89"
    assert items[0]["amount"] == "0.89"


@respx.mock
async def test_game_catalogue_swallows_errors(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Upstream 500 → empty list, not a 5xx — the picker shows "пусто" UX,
    not a tripped error boundary."""
    respx.get(f"{G2B_BASE}/games/broken/catalogue").mock(
        return_value=httpx.Response(500, text="boom")
    )
    admin = await _login_admin(integration_client, db_session, tg_id=702)
    r = await integration_client.get(
        "/api/v1/admin/integrations/g2b/games/broken/catalogue",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200
    assert r.json()["items"] == []


# ---------- fields ----------


@respx.mock
async def test_game_fields_returns_required_fields(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    respx.post(f"{G2B_BASE}/games/fields").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "200",
                "info": {
                    "fields": ["userid", "serverid"],
                    "notes": "Not available for Indonesia users",
                },
            },
        )
    )
    admin = await _login_admin(integration_client, db_session, tg_id=703)
    r = await integration_client.get(
        "/api/v1/admin/integrations/g2b/games/mlbb/fields",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["fields"] == ["userid", "serverid"]
    assert body["notes"] == "Not available for Indonesia users"


# ---------- check-player ----------


@respx.mock
async def test_check_player_valid_returns_name(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    respx.post(f"{G2B_BASE}/games/checkPlayerId").mock(
        return_value=httpx.Response(
            200,
            json={"valid": "valid", "name": "John Doe", "openid": "41581795132966184"},
        )
    )
    admin = await _login_admin(integration_client, db_session, tg_id=704)
    r = await integration_client.post(
        "/api/v1/admin/integrations/g2b/games/mlbb/check-player",
        headers={"Authorization": f"Bearer {admin}"},
        json={"player_id": "123456789", "server_id": "2001"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["name"] == "John Doe"


@respx.mock
async def test_check_player_invalid_returns_reason(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    respx.post(f"{G2B_BASE}/games/checkPlayerId").mock(
        return_value=httpx.Response(
            200,
            json={"valid": "invalid", "message": "player not found"},
        )
    )
    admin = await _login_admin(integration_client, db_session, tg_id=705)
    r = await integration_client.post(
        "/api/v1/admin/integrations/g2b/games/mlbb/check-player",
        headers={"Authorization": f"Bearer {admin}"},
        json={"player_id": "999"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert "player not found" in body["reason"]


# ---------- sku search ----------


@pytest.fixture
async def _seed_skus(db_session: AsyncSession) -> tuple[str, str]:
    category = Category(
        id=new_id(),
        slug="games-sk",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="pubg-sk",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="PUBG")],
    )
    product = Product(
        id=new_id(),
        slug="pubg-uc",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="PUBG UC")],
    )
    sku_a = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="pubg-60uc",
        denomination="60",
        region="WW",
        price_usd=Decimal("1.00"),
        sort_order=10,
        active=True,
    )
    sku_b = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="pubg-180uc",
        denomination="180",
        region="WW",
        price_usd=Decimal("3.00"),
        sort_order=20,
        active=True,
    )
    db_session.add_all([category, brand, product, sku_a, sku_b])
    await db_session.commit()
    return sku_a.id, sku_b.id


async def test_skus_search_returns_product_name(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_skus: tuple[str, str],
) -> None:
    admin = await _login_admin(integration_client, db_session, tg_id=706)
    headers = {"Authorization": f"Bearer {admin}"}

    full = await integration_client.get(
        "/api/v1/admin/catalog/skus/search",
        headers=headers,
    )
    assert full.status_code == 200, full.text
    body = full.json()
    assert len(body) >= 2
    assert all("product_name" in row for row in body)

    narrow = await integration_client.get(
        "/api/v1/admin/catalog/skus/search?q=60",
        headers=headers,
    )
    assert narrow.status_code == 200
    rows = narrow.json()
    assert len(rows) == 1
    assert rows[0]["sku_code"] == "pubg-60uc"
    assert rows[0]["product_name"] == "PUBG UC"

    by_product = await integration_client.get(
        "/api/v1/admin/catalog/skus/search?q=PUBG",
        headers=headers,
    )
    assert by_product.status_code == 200
    assert len(by_product.json()) == 2


async def test_skus_search_by_id_ignores_the_page_window(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_skus: tuple[str, str],
) -> None:
    """``sku_id`` must return the exact row even when the default listing
    would never include it.

    The mapping edit page prefills its SKU step through this endpoint; with
    183 SKUs on prod the edited SKU sat at position 130 of a 30-row default
    page, the prefill silently missed, and the save button stayed disabled
    forever. ``limit=1`` below simulates that window being too small.
    """
    _, sku_b_id = _seed_skus
    admin = await _login_admin(integration_client, db_session, tg_id=707)
    headers = {"Authorization": f"Bearer {admin}"}

    by_id = await integration_client.get(
        f"/api/v1/admin/catalog/skus/search?sku_id={sku_b_id}&limit=1",
        headers=headers,
    )
    assert by_id.status_code == 200, by_id.text
    rows = by_id.json()
    assert len(rows) == 1
    assert rows[0]["id"] == sku_b_id
    assert "product_name" in rows[0]

    missing = await integration_client.get(
        "/api/v1/admin/catalog/skus/search?sku_id=01900000-0000-7000-8000-000000000000",
        headers=headers,
    )
    assert missing.status_code == 200
    assert missing.json() == []
