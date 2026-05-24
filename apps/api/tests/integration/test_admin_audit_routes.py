"""Integration tests for the unified audit feed admin endpoint.

Focus on the admin_only filter (Sprint 4, ADR-0017): an Activity view that
shows only events whose actor is an admin (``actor LIKE 'admin:%'``).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.orders.models import Order, OrderEvent
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


async def _make_order_with_event(db: AsyncSession, *, kind: str, actor: str | None) -> str:
    user_id = str(uuid.uuid4())
    order_id = str(uuid.uuid4())
    db.add(
        User(
            id=user_id,
            email=f"u-{user_id[:8]}@example.com",
            locale="ru",
            display_currency="USD",
            roles=[],
        )
    )
    await db.flush()
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            guest_email=None,
            status="pending_payment",
            currency="USD",
            total_usd=Decimal("1.00"),
            total_charged=Decimal("1.00"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db.flush()
    db.add(
        OrderEvent(
            id=str(uuid.uuid4()),
            order_id=order_id,
            kind=kind,
            payload={},
            actor=actor,
        )
    )
    await db.commit()
    return order_id


# ---------- auth gate ----------


async def test_audit_requires_token(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/admin/audit")
    assert r.status_code == 401


async def test_audit_forbids_non_admin(integration_client: AsyncClient) -> None:
    token = await _login(integration_client, tg_id=200)
    r = await integration_client.get(
        "/api/v1/admin/audit", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403


# ---------- admin_only filter ----------


async def test_admin_only_filters_to_admin_actors(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    admin_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    await _make_order_with_event(db_session, kind="order.cancelled", actor=f"admin:{admin_id}")
    await _make_order_with_event(db_session, kind="order.created", actor=f"user:{user_id}")
    await _make_order_with_event(db_session, kind="order.expired", actor="system:expiry")

    r = await integration_client.get("/api/v1/admin/audit?admin_only=true", headers=_admin_headers)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    actors = {item["actor"] for item in items if item["actor"] is not None}
    assert all(a.startswith("admin:") for a in actors)
    assert any(a == f"admin:{admin_id}" for a in actors)


async def test_admin_only_default_false_returns_all(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """When admin_only isn't set, the feed still returns everything (existing behaviour)."""
    user_id = str(uuid.uuid4())
    await _make_order_with_event(db_session, kind="order.created", actor=f"user:{user_id}")

    r = await integration_client.get("/api/v1/admin/audit", headers=_admin_headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(item["actor"] == f"user:{user_id}" for item in items)


async def test_admin_only_excludes_system_events(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    await _make_order_with_event(db_session, kind="order.expired", actor="system:expiry")
    r = await integration_client.get("/api/v1/admin/audit?admin_only=true", headers=_admin_headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(item["actor"] is None or not item["actor"].startswith("system:") for item in items)
