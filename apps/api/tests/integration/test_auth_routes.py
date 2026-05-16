"""Integration tests for the ``/api/v1/auth/*`` routes."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from yupay.core.config import get_settings

pytestmark = pytest.mark.asyncio


BOT_TOKEN = "123456:TEST"  # matches the conftest-managed TELEGRAM_BOT_TOKEN


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


def _sign_widget(fields: dict[str, str]) -> dict[str, str]:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hashlib.sha256(BOT_TOKEN.encode("utf-8")).digest()
    return {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}


@pytest.fixture
def fixed_now():
    """A fresh ``auth_date`` per test (real time, no clock freezing).

    JWT verification uses real wall time, so freezing the clock would either expire the
    tokens immediately or break ``exp`` comparisons. Telegram only checks the age of
    ``auth_date`` against ``max_age_seconds`` — a real timestamp is fine.
    """
    return int(time.time())


async def _login_via_webapp(client: AsyncClient, fixed_now: int) -> dict[str, Any]:
    user_json = json.dumps(
        {"id": 777, "first_name": "Yu", "username": "yu_user", "language_code": "ru"},
        separators=(",", ":"),
    )
    init_data = _sign_init_data({"user": user_json, "auth_date": str(fixed_now), "query_id": "q1"})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


async def test_telegram_webapp_login_creates_user_and_session(
    integration_client: AsyncClient, fixed_now: int
) -> None:
    body = await _login_via_webapp(integration_client, fixed_now)
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == get_settings().jwt_access_ttl_seconds


async def test_telegram_webapp_returns_same_user_on_repeat_login(
    integration_client: AsyncClient, fixed_now: int
) -> None:
    first = await _login_via_webapp(integration_client, fixed_now)
    second = await _login_via_webapp(integration_client, fixed_now)
    # Both sessions exist but they belong to the same user.
    me1 = await integration_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {first['access_token']}"},
    )
    me2 = await integration_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {second['access_token']}"},
    )
    assert me1.status_code == 200
    assert me2.status_code == 200
    assert me1.json()["id"] == me2.json()["id"]


async def test_telegram_webapp_rejects_tampered_hash(
    integration_client: AsyncClient, fixed_now: int
) -> None:
    user_json = json.dumps({"id": 7, "first_name": "Z"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(fixed_now)})
    tampered = init_data[:-1] + ("0" if init_data[-1] != "0" else "1")
    r = await integration_client.post("/api/v1/auth/telegram/webapp", json={"init_data": tampered})
    assert r.status_code == 401


async def test_telegram_widget_login(integration_client: AsyncClient, fixed_now: int) -> None:
    payload = _sign_widget(
        {
            "id": "42",
            "first_name": "Web",
            "username": "web_user",
            "auth_date": str(fixed_now),
        }
    )
    typed_payload = {
        "id": int(payload["id"]),
        "first_name": payload["first_name"],
        "username": payload["username"],
        "auth_date": int(payload["auth_date"]),
        "hash": payload["hash"],
    }
    r = await integration_client.post("/api/v1/auth/telegram/widget", json=typed_payload)
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


async def test_guest_checkout_returns_token(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        "/api/v1/auth/guest", json={"email": "  Test+Yu@Example.com "}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "Guest"
    assert body["expires_in"] == get_settings().jwt_guest_ttl_seconds
    assert body["access_token"]


async def test_refresh_rotates_token(integration_client: AsyncClient, fixed_now: int) -> None:
    first = await _login_via_webapp(integration_client, fixed_now)
    r = await integration_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert r.status_code == 200
    body = r.json()
    # New refresh token issued; old one must now be revoked.
    assert body["refresh_token"] != first["refresh_token"]

    # Re-using the old refresh triggers the trip-wire.
    replay = await integration_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert replay.status_code == 401


async def test_logout_is_idempotent(integration_client: AsyncClient, fixed_now: int) -> None:
    tokens = await _login_via_webapp(integration_client, fixed_now)
    r1 = await integration_client.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    r2 = await integration_client.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert r1.status_code == 204
    assert r2.status_code == 204


async def test_me_requires_bearer_token(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/auth/me")
    assert r.status_code == 401


async def test_me_returns_current_user(integration_client: AsyncClient, fixed_now: int) -> None:
    tokens = await _login_via_webapp(integration_client, fixed_now)
    r = await integration_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["locale"] == "ru"
    assert body["display_name"] == "Yu"
