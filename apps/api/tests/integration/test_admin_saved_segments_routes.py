"""Integration tests for per-admin saved-segment bookmarks.

POST /admin/segments   — create
GET /admin/segments    — list own
DELETE /admin/segments/{id} — remove own
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str], token: str = BOT_TOKEN) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login(client: AsyncClient, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "Admin"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> None:
    from sqlalchemy import select

    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()


@pytest.fixture
async def _admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    token = await _login(integration_client, tg_id=42)
    await _grant_admin(db_session, tg_id=42)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def _other_admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    token = await _login(integration_client, tg_id=84)
    await _grant_admin(db_session, tg_id=84)
    return {"Authorization": f"Bearer {token}"}


# ---------- auth gate ----------


async def test_segments_requires_token(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/admin/segments")
    assert r.status_code == 401


async def test_segments_forbids_non_admin(integration_client: AsyncClient) -> None:
    token = await _login(integration_client, tg_id=300)
    r = await integration_client.get(
        "/api/v1/admin/segments", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403


# ---------- happy path ----------


async def test_create_and_list_segment(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    r = await integration_client.post(
        "/api/v1/admin/segments",
        headers=_admin_headers,
        json={
            "name": "Stuck Click >60",
            "path": "/payments/triage",
            "params": {"tab": "stuck", "after": "60"},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Stuck Click >60"
    assert body["path"] == "/payments/triage"
    assert body["params"] == {"tab": "stuck", "after": "60"}

    r = await integration_client.get("/api/v1/admin/segments", headers=_admin_headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(s["name"] == "Stuck Click >60" for s in items)


async def test_isolation_between_admins(
    integration_client: AsyncClient,
    _admin_headers: dict[str, str],
    _other_admin_headers: dict[str, str],
) -> None:
    """An admin doesn't see another admin's saved segments."""
    r = await integration_client.post(
        "/api/v1/admin/segments",
        headers=_admin_headers,
        json={"name": "Mine", "path": "/orders", "params": {}},
    )
    assert r.status_code == 201

    r = await integration_client.get("/api/v1/admin/segments", headers=_other_admin_headers)
    assert r.status_code == 200
    assert all(s["name"] != "Mine" for s in r.json()["items"])


async def test_duplicate_name_returns_409(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    payload = {"name": "Dup", "path": "/orders", "params": {}}
    r = await integration_client.post(
        "/api/v1/admin/segments", headers=_admin_headers, json=payload
    )
    assert r.status_code == 201
    r = await integration_client.post(
        "/api/v1/admin/segments", headers=_admin_headers, json=payload
    )
    assert r.status_code == 409


async def test_delete_own_segment(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    r = await integration_client.post(
        "/api/v1/admin/segments",
        headers=_admin_headers,
        json={"name": "To delete", "path": "/orders", "params": {}},
    )
    seg_id = r.json()["id"]

    r = await integration_client.delete(f"/api/v1/admin/segments/{seg_id}", headers=_admin_headers)
    assert r.status_code == 204

    r = await integration_client.get("/api/v1/admin/segments", headers=_admin_headers)
    assert all(s["id"] != seg_id for s in r.json()["items"])


async def test_delete_someone_elses_segment_returns_404(
    integration_client: AsyncClient,
    _admin_headers: dict[str, str],
    _other_admin_headers: dict[str, str],
) -> None:
    """Crossing owners must look like "not found" — never reveal another admin's ids."""
    r = await integration_client.post(
        "/api/v1/admin/segments",
        headers=_admin_headers,
        json={"name": "Private", "path": "/orders", "params": {}},
    )
    seg_id = r.json()["id"]

    r = await integration_client.delete(
        f"/api/v1/admin/segments/{seg_id}", headers=_other_admin_headers
    )
    assert r.status_code == 404


# ---------- input validation ----------


async def test_name_too_long_rejected(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    r = await integration_client.post(
        "/api/v1/admin/segments",
        headers=_admin_headers,
        json={"name": "x" * 200, "path": "/orders", "params": {}},
    )
    assert r.status_code == 422


async def test_path_must_be_admin_route(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """Avoid bookmarking external URLs — a saved segment is meant for the admin SPA."""
    r = await integration_client.post(
        "/api/v1/admin/segments",
        headers=_admin_headers,
        json={"name": "Bad", "path": "https://evil.example.com", "params": {}},
    )
    assert r.status_code == 422
