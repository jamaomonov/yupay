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

pytestmark = pytest.mark.asyncio


BOT_TOKEN = "123456:TEST"  # matches the conftest-managed TELEGRAM_BOT_TOKEN


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login(client: AsyncClient) -> str:
    """Log in a fresh Telegram user and return the bearer access token."""
    user_json = json.dumps(
        {"id": 555, "first_name": "Lo", "username": "lo_user", "language_code": "ru"},
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
