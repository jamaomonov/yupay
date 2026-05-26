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
    respx.get(f"{G2B_BASE}/products?page=1&limit=200").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
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
                "items": [
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
        return_value=httpx.Response(200, json={"items": [{"code": "ff", "name": "Free Fire"}]})
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
