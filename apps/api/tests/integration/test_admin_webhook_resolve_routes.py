"""Integration tests for admin webhook resolve action.

POST /admin/webhooks/{id}/mark-resolved lets an operator acknowledge a
rejected or stuck webhook record so it stops surfacing as "broken".
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.payments.models import PaymentWebhook
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


async def _grant_admin(db: AsyncSession, tg_id: int, *, email: str | None = None) -> None:
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    values: dict[str, object] = {"roles": ["admin"]}
    if email is not None:
        values["email"] = email
    await db.execute(update(User).where(User.id == user_id).values(**values))
    await db.commit()


@pytest.fixture
async def admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    token = await _login(integration_client, tg_id=4242)
    await _grant_admin(db_session, tg_id=4242, email="ops@yupay.test")
    return {"Authorization": f"Bearer {token}"}


async def _make_webhook(
    db: AsyncSession,
    *,
    signature_ok: bool = True,
    processed: bool = True,
    payload: dict[str, object] | None = None,
) -> str:
    wid = str(uuid.uuid4())
    received = datetime.now(UTC) - timedelta(minutes=5)
    db.add(
        PaymentWebhook(
            id=wid,
            provider="stub",
            external_event_id=f"evt_{wid[:8]}",
            received_at=received,
            processed_at=received if processed else None,
            payload=payload or {"ok": True},
            signature_ok=signature_ok,
        )
    )
    await db.commit()
    return wid


# ---------- auth gates ----------


async def test_resolve_requires_token(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        f"/api/v1/admin/webhooks/{uuid.uuid4()}/mark-resolved",
        json={"reason": "looked at it"},
    )
    assert r.status_code == 401


async def test_resolve_forbids_non_admin(integration_client: AsyncClient) -> None:
    token = await _login(integration_client, tg_id=999)
    r = await integration_client.post(
        f"/api/v1/admin/webhooks/{uuid.uuid4()}/mark-resolved",
        json={"reason": "looked at it"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


# ---------- happy paths ----------


async def test_resolve_rejected_webhook_stamps_admin_block(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    admin_headers: dict[str, str],
) -> None:
    wid = await _make_webhook(
        db_session,
        signature_ok=False,
        processed=False,
        payload={"body": "garbage"},
    )

    r = await integration_client.post(
        f"/api/v1/admin/webhooks/{wid}/mark-resolved",
        json={"reason": "looks like a probe — not a real provider"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == wid
    assert body["processed_at"] is not None  # should be stamped now
    assert body["payload"]["_admin_resolved"]["actor"] == "ops@yupay.test"
    assert "probe" in body["payload"]["_admin_resolved"]["reason"]


async def test_resolve_idempotent_overwrites_reason(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    admin_headers: dict[str, str],
) -> None:
    wid = await _make_webhook(db_session, signature_ok=False, processed=False)

    r1 = await integration_client.post(
        f"/api/v1/admin/webhooks/{wid}/mark-resolved",
        json={"reason": "first"},
        headers=admin_headers,
    )
    assert r1.status_code == 200
    r2 = await integration_client.post(
        f"/api/v1/admin/webhooks/{wid}/mark-resolved",
        json={"reason": "more detailed second reason"},
        headers=admin_headers,
    )
    assert r2.status_code == 200
    assert "second" in r2.json()["payload"]["_admin_resolved"]["reason"]


async def test_resolve_keeps_existing_processed_at(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    admin_headers: dict[str, str],
) -> None:
    wid = await _make_webhook(db_session, signature_ok=True, processed=True)
    before = (
        await db_session.execute(
            select(PaymentWebhook.processed_at).where(PaymentWebhook.id == wid)
        )
    ).scalar_one()

    r = await integration_client.post(
        f"/api/v1/admin/webhooks/{wid}/mark-resolved",
        json={"reason": "duplicate after manual replay"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    after = (
        await db_session.execute(
            select(PaymentWebhook.processed_at).where(PaymentWebhook.id == wid)
        )
    ).scalar_one()
    assert before == after, "processed_at must not move once it's set"


# ---------- bad inputs ----------


async def test_resolve_blank_reason_is_rejected(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    admin_headers: dict[str, str],
) -> None:
    wid = await _make_webhook(db_session)
    r = await integration_client.post(
        f"/api/v1/admin/webhooks/{wid}/mark-resolved",
        json={"reason": "   "},
        headers=admin_headers,
    )
    assert r.status_code == 422


async def test_resolve_unknown_webhook_is_404(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    r = await integration_client.post(
        f"/api/v1/admin/webhooks/{uuid.uuid4()}/mark-resolved",
        json={"reason": "nope"},
        headers=admin_headers,
    )
    assert r.status_code == 404
