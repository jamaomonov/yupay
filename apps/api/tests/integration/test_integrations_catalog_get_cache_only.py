"""``GET /admin/integrations/catalog`` reads the cache only — never a supplier.

AGENTS.md §10 forbids a synchronous supplier call inside a request handler on
the money path; this admin picker isn't on that path either way, but the
contract for it is explicit: the picker polls the cache, and only the two
POST sync endpoints (hourly job or on-demand) ever reach a supplier client.

Every supplier's API key is configured here (so a wrongly-wired GET handler
would actually have somewhere to call), and the whole test runs inside a bare
``@respx.mock`` block with **no routes registered** — respx blocks all real
outbound HTTP in that scope, so a stray supplier call would fail the request
outright rather than passing unnoticed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.modules.integrations import service as svc
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


@pytest.fixture(autouse=True)
def _all_suppliers_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("G2B_API_KEY", "test-key")
    monkeypatch.setenv("G2B_BASE_URL", "https://g2b.getcache.test/v1")
    monkeypatch.setenv("NOVA_API_KEY", "test-key")
    monkeypatch.setenv("NOVA_BASE_URL", "https://nova.getcache.test")
    monkeypatch.setenv("GENGINE_API_KEY", "test-key")
    monkeypatch.setenv("GENGINE_BASE_URL", "https://gengine.getcache.test/v2.1")
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
async def test_get_catalog_never_calls_a_supplier(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    # Seed rows directly — the point is that the GET handler must not need to
    # go fetch them itself.
    await svc.upsert_catalog_entry(
        db_session,
        supplier_slug="nova",
        kind="game",
        external_id="mobile_legends_ru",
        title="Mobile Legends (RU)",
        raw={"category_id": "mobile_legends_ru"},
    )
    await svc.upsert_catalog_entry(
        db_session,
        supplier_slug="nova",
        kind="game_denom",
        external_id="275_diamonds",
        title="275 Diamonds",
        raw={"offer_id": "275_diamonds"},
        parent_external_id="mobile_legends_ru",
    )
    await db_session.commit()

    admin = await _login_admin(integration_client, db_session, tg_id=901)
    headers = {"Authorization": f"Bearer {admin}"}

    listing = await integration_client.get(
        "/api/v1/admin/integrations/catalog?supplier_slug=nova", headers=headers
    )
    assert listing.status_code == 200, listing.text
    assert len(listing.json()["items"]) == 2

    denoms = await integration_client.get(
        "/api/v1/admin/integrations/catalog"
        "?supplier_slug=nova&kind=game_denom&parent_external_id=mobile_legends_ru",
        headers=headers,
    )
    assert denoms.status_code == 200, denoms.text
    assert len(denoms.json()["items"]) == 1
