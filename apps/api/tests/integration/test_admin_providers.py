"""Admin list + set-state endpoints for logical payment providers.

Covers ``GET /admin/payments/providers`` (one row per logical provider,
grouping Click's two surface slugs) and ``PUT
/admin/payments/providers/{provider}/state`` (writes every slug of the group,
returns the updated summary, 404s on an unknown provider).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login_user(client: AsyncClient, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> str:
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return user_id


async def _admin_token(client: AsyncClient, db: AsyncSession, tg_id: int) -> str:
    token = await _login_user(client, tg_id=tg_id)
    await _grant_admin(db, tg_id=tg_id)
    return token


async def test_admin_can_list_and_set_provider_state(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _admin_token(integration_client, db_session, tg_id=601)
    h = {"Authorization": f"Bearer {token}"}

    lst = await integration_client.get("/api/v1/admin/payments/providers", headers=h)
    assert lst.status_code == 200
    names = {p["provider"] for p in lst.json()["providers"]}
    assert {"click", "payme", "uzum", "octo", "crypto"} <= names
    click = next(p for p in lst.json()["providers"] if p["provider"] == "click")
    assert click["slugs"] == ["click", "click_miniapp"]
    assert click["state"] == "active"

    put = await integration_client.put(
        "/api/v1/admin/payments/providers/click/state",
        headers={**h, "Idempotency-Key": "set-1-set-1-set-1"},
        json={"state": "maintenance"},
    )
    assert put.status_code == 200, put.text
    assert put.json()["state"] == "maintenance"

    lst2 = await integration_client.get("/api/v1/admin/payments/providers", headers=h)
    click2 = next(p for p in lst2.json()["providers"] if p["provider"] == "click")
    assert click2["state"] == "maintenance"
    assert click2["changed_at"] is not None


async def test_set_state_unknown_provider_404(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _admin_token(integration_client, db_session, tg_id=602)
    r = await integration_client.put(
        "/api/v1/admin/payments/providers/paypal/state",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "x-idempotency-key",
        },
        json={"state": "disabled"},
    )
    assert r.status_code == 404
