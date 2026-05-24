"""Integration tests for the payments triage endpoint.

GET /admin/payments/triage returns two focused buckets:
- stuck_pending payments (status=pending older than threshold)
- failed_webhooks (signature_ok=False or stuck unprocessed)
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
from yupay.modules.orders.models import Order
from yupay.modules.payments.models import Payment, PaymentWebhook
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


async def _make_order_with_payment(
    db: AsyncSession,
    *,
    payment_status: str = "pending",
    payment_age_minutes: int = 0,
    with_user: bool = True,
) -> tuple[str, str, str | None]:
    """Return (order_id, payment_id, user_id_or_None)."""
    user_id: str | None = None
    if with_user:
        user_id = str(uuid.uuid4())
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
    order_id = str(uuid.uuid4())
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            guest_email=None if user_id else f"guest-{order_id[:8]}@example.com",
            status="pending_payment",
            currency="USD",
            total_usd=Decimal("10.00"),
            total_charged=Decimal("10.00"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db.flush()
    payment_id = str(uuid.uuid4())
    created = datetime.now(UTC) - timedelta(minutes=payment_age_minutes)
    db.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider="stub",
            status=payment_status,
            amount=Decimal("10.00"),
            currency="USD",
            created_at=created,
            updated_at=created,
        )
    )
    await db.commit()
    return order_id, payment_id, user_id


async def _make_webhook(
    db: AsyncSession,
    *,
    signature_ok: bool = True,
    processed: bool = True,
    received_minutes_ago: int = 5,
) -> str:
    wid = str(uuid.uuid4())
    received = datetime.now(UTC) - timedelta(minutes=received_minutes_ago)
    db.add(
        PaymentWebhook(
            id=wid,
            provider="stub",
            external_event_id=f"evt_{wid[:8]}",
            received_at=received,
            processed_at=received if processed else None,
            payload={"ok": True},
            signature_ok=signature_ok,
        )
    )
    await db.commit()
    return wid


# ---------- auth gate ----------


async def test_triage_requires_token(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/admin/payments/triage")
    assert r.status_code == 401


async def test_triage_forbids_non_admin(integration_client: AsyncClient) -> None:
    token = await _login(integration_client, tg_id=200)
    r = await integration_client.get(
        "/api/v1/admin/payments/triage",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


# ---------- response shape ----------


async def test_triage_returns_both_buckets(
    integration_client: AsyncClient,
    _admin_headers: dict[str, str],
) -> None:
    r = await integration_client.get("/api/v1/admin/payments/triage", headers=_admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) >= {"stuck_pending", "failed_webhooks", "threshold_minutes"}
    assert isinstance(body["stuck_pending"], list)
    assert isinstance(body["failed_webhooks"], list)


# ---------- stuck pending ----------


async def test_stuck_payment_appears_only_over_threshold(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    # Two pending payments: one fresh, one old.
    _, fresh_pid, _ = await _make_order_with_payment(db_session, payment_age_minutes=5)
    _, old_pid, user_id = await _make_order_with_payment(db_session, payment_age_minutes=120)
    r = await integration_client.get(
        "/api/v1/admin/payments/triage?stuck_after_minutes=30",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    ids = [p["id"] for p in r.json()["stuck_pending"]]
    assert old_pid in ids
    assert fresh_pid not in ids
    row = next(p for p in r.json()["stuck_pending"] if p["id"] == old_pid)
    assert row["user_id"] == user_id
    assert row["waiting_minutes"] >= 120


async def test_succeeded_payment_not_listed(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    _, paid_pid, _ = await _make_order_with_payment(
        db_session, payment_status="succeeded", payment_age_minutes=120
    )
    r = await integration_client.get(
        "/api/v1/admin/payments/triage?stuck_after_minutes=30",
        headers=_admin_headers,
    )
    assert r.status_code == 200
    assert paid_pid not in [p["id"] for p in r.json()["stuck_pending"]]


# ---------- failed webhooks ----------


async def test_failed_webhook_with_bad_signature_appears(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    wid = await _make_webhook(db_session, signature_ok=False, processed=False)
    r = await integration_client.get("/api/v1/admin/payments/triage", headers=_admin_headers)
    assert r.status_code == 200, r.text
    failed = r.json()["failed_webhooks"]
    assert any(w["id"] == wid for w in failed)
    row = next(w for w in failed if w["id"] == wid)
    assert row["signature_ok"] is False


async def test_processed_ok_webhook_not_listed(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    wid = await _make_webhook(db_session, signature_ok=True, processed=True)
    r = await integration_client.get("/api/v1/admin/payments/triage", headers=_admin_headers)
    assert r.status_code == 200
    failed = r.json()["failed_webhooks"]
    assert all(w["id"] != wid for w in failed)


# ---------- input validation ----------


async def test_threshold_too_small_rejected(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    r = await integration_client.get(
        "/api/v1/admin/payments/triage?stuck_after_minutes=0",
        headers=_admin_headers,
    )
    assert r.status_code == 422
