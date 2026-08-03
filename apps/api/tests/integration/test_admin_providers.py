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


async def test_set_state_idempotency_key_replays_cached_response(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A repeated ``PUT`` with the same ``Idempotency-Key`` replays the first
    response verbatim instead of re-running ``set_provider_state``.

    We mutate the provider's state directly (via ``provider_state``, bypassing
    the route) between the two calls, and send a *different* body on the
    replay — if the handler re-executed, the second response and the DB rows
    would both reflect that mutation. They don't.
    """
    from yupay.modules.payments import provider_state as ps

    token = await _admin_token(integration_client, db_session, tg_id=603)
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "replay-1-replay-1",
    }

    first = await integration_client.put(
        "/api/v1/admin/payments/providers/click/state",
        headers=headers,
        json={"state": "maintenance"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["state"] == "maintenance"

    # Mutate the underlying state out-of-band so a live re-execution would be
    # observably different from the cached first response.
    await ps.set_logical_state(db_session, provider="click", state="active", changed_by=None)
    await db_session.commit()

    replay = await integration_client.put(
        "/api/v1/admin/payments/providers/click/state",
        headers=headers,
        json={"state": "disabled"},  # different body — the replay must ignore it
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert replay.json()["state"] == "maintenance"

    # The out-of-band mutation is still in place — the replay never called
    # ``set_provider_state`` a second time.
    states = await ps.get_states(db_session, ["click", "click_miniapp"])
    assert states == {"click": "active", "click_miniapp": "active"}
