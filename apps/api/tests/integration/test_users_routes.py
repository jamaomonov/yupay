"""Integration tests for the ``/api/v1/users/*`` routes."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio


BOT_TOKEN = "123456:TEST"  # matches the conftest-managed TELEGRAM_BOT_TOKEN


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login(client: AsyncClient, tg_id: int = 555) -> str:
    """Log in a fresh Telegram user and return the bearer access token."""
    user_json = json.dumps(
        {"id": tg_id, "first_name": "Lo", "username": "lo_user", "language_code": "ru"},
        separators=(",", ":"),
    )
    init_data = _sign_init_data(
        {"user": user_json, "auth_date": str(int(time.time())), "query_id": "q1"}
    )
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    token: str = body["access_token"]
    return token


async def _grant_admin(db_session: AsyncSession, tg_id: int) -> str:
    """Promote the Telegram-linked user to ``admin`` and return their user id."""
    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    return str(user_id)


async def test_patch_me_requires_auth(integration_client: AsyncClient) -> None:
    r = await integration_client.patch("/api/v1/users/me", json={"locale": "en"})
    assert r.status_code == 401


async def test_patch_me_updates_locale(integration_client: AsyncClient) -> None:
    token = await _login(integration_client)
    r = await integration_client.patch(
        "/api/v1/users/me",
        json={"locale": "en"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["locale"] == "en"


async def test_patch_me_updates_each_supported_locale(integration_client: AsyncClient) -> None:
    token = await _login(integration_client)
    for loc in ("uz", "en", "ru"):
        r = await integration_client.patch(
            "/api/v1/users/me",
            json={"locale": loc},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["locale"] == loc


async def test_patch_me_rejects_unsupported_locale(integration_client: AsyncClient) -> None:
    token = await _login(integration_client)
    # ``fr`` is a valid BCP-47 tag but the storefront ships no UI for it, so the
    # Literal in ``UpdateMeIn`` rejects it at the schema layer (422).
    r = await integration_client.patch(
        "/api/v1/users/me",
        json={"locale": "fr"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422, r.text


async def test_patch_me_updates_display_currency(integration_client: AsyncClient) -> None:
    token = await _login(integration_client)
    r = await integration_client.patch(
        "/api/v1/users/me",
        json={"display_currency": "UZS"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["display_currency"] == "UZS"


# ---------- B1: admin listing must survive a malformed ``roles`` value ----------


async def test_admin_list_users_coerces_malformed_roles_to_empty_list(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A legacy row with ``roles = '{}'::jsonb`` (a JSON object, not a list) must
    not 500 the admin listing — it should serialize as ``roles: []``."""
    admin_token = await _login(integration_client, tg_id=42)
    await _grant_admin(db_session, tg_id=42)

    other_token = await _login(integration_client, tg_id=777)
    # Bypass app-level validation to simulate the legacy/edge DB state directly.
    await db_session.execute(
        text("UPDATE users SET roles = '{}'::jsonb WHERE id = :id"),
        {"id": _decode_user_id(other_token)},
    )
    await db_session.commit()

    r = await integration_client.get(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[_decode_user_id(other_token)]["roles"] == []


def _decode_user_id(access_token: str) -> str:
    """Pull ``sub`` (the user id) out of the JWT without verifying signature —
    test-only convenience, the token was just minted by our own login flow."""
    import base64

    payload_b64 = access_token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    sub: str = payload["sub"]
    return sub
