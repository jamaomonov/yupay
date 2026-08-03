"""Integration tests for the admin per-provider analytics detail endpoint.

``GET /admin/payments/providers/{provider}`` returns four blocks for a
logical provider: ``summary`` (Task 5's ``AdminProviderSummary``), ``volume``
(succeeded-bucket amount+count by currency), ``success_rate``
(succeeded/failed/pending + %), ``recent`` (last N payments, no PII), and
``incidents`` (stuck_pending + failed_webhooks, mirroring
``admin.triage_payments``).
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
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.orders.models import Order
from yupay.modules.payments.models import Payment, PaymentWebhook
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


async def _grant_admin(db: AsyncSession, tg_id: int) -> None:
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()


async def _admin_token(client: AsyncClient, db: AsyncSession, tg_id: int = 701) -> str:
    token = await _login_user(client, tg_id=tg_id)
    await _grant_admin(db, tg_id=tg_id)
    return token


async def _seed_payment(
    db: AsyncSession,
    *,
    provider: str,
    payment_status: str,
    currency: str = "USD",
    amount: Decimal = Decimal("10.00"),
    age_minutes: int = 0,
) -> str:
    """Insert an Order + Payment row and return the payment id."""
    order_id = str(uuid.uuid4())
    db.add(
        Order(
            id=order_id,
            user_id=None,
            guest_email=f"guest-{order_id[:8]}@example.com",
            status="pending_payment",
            currency=currency,
            total_usd=amount,
            total_charged=amount,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db.flush()
    payment_id = str(uuid.uuid4())
    created = datetime.now(UTC) - timedelta(minutes=age_minutes)
    db.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider=provider,
            status=payment_status,
            amount=amount,
            currency=currency,
            created_at=created,
            updated_at=created,
        )
    )
    await db.commit()
    return payment_id


async def _seed_webhook(
    db: AsyncSession, *, provider: str, signature_ok: bool, processed: bool
) -> str:
    wid = str(uuid.uuid4())
    db.add(
        PaymentWebhook(
            id=wid,
            provider=provider,
            external_event_id=f"evt_{wid[:8]}",
            payload={"ok": True},
            signature_ok=signature_ok,
            processed_at=None if not processed else datetime.now(UTC),
        )
    )
    await db.commit()
    return wid


async def test_provider_detail_returns_analytics_blocks(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _admin_token(integration_client, db_session)
    h = {"Authorization": f"Bearer {token}"}

    await _seed_payment(db_session, provider="payme", payment_status="succeeded", currency="UZS")
    await _seed_payment(db_session, provider="payme", payment_status="succeeded", currency="USD")
    await _seed_payment(db_session, provider="payme", payment_status="failed", currency="UZS")
    await _seed_payment(
        db_session,
        provider="payme",
        payment_status="pending",
        currency="UZS",
        age_minutes=120,
    )
    await _seed_webhook(db_session, provider="payme", signature_ok=False, processed=False)

    r = await integration_client.get(
        "/api/v1/admin/payments/providers/payme?window=30d",
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["summary"]["provider"] == "payme"

    volume_by_currency = {row["currency"]: row for row in body["volume"]}
    assert volume_by_currency["UZS"]["count"] == 1
    assert volume_by_currency["USD"]["count"] == 1
    assert Decimal(volume_by_currency["UZS"]["amount"]) == Decimal("10.00")

    assert body["success_rate"] == {
        "succeeded": 2,
        "failed": 1,
        "pending": 1,
        "success_pct": 50.0,
    }

    assert len(body["recent"]) == 4
    for row in body["recent"]:
        assert set(row.keys()) == {"id", "order_id", "status", "amount", "currency", "created_at"}

    assert body["incidents"] == {"stuck_pending": 1, "failed_webhooks": 1}


async def test_provider_detail_zero_payments_ok(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _admin_token(integration_client, db_session, tg_id=702)
    r = await integration_client.get(
        "/api/v1/admin/payments/providers/octo",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["provider"] == "octo"
    assert body["volume"] == []
    assert body["success_rate"] == {
        "succeeded": 0,
        "failed": 0,
        "pending": 0,
        "success_pct": 0.0,
    }
    assert body["recent"] == []
    assert body["incidents"] == {"stuck_pending": 0, "failed_webhooks": 0}


async def test_provider_detail_unknown_provider_404(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _admin_token(integration_client, db_session, tg_id=703)
    r = await integration_client.get(
        "/api/v1/admin/payments/providers/paypal",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


async def test_provider_detail_window_filters_old_payments(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _admin_token(integration_client, db_session, tg_id=704)
    old = datetime.now(UTC) - timedelta(days=60)
    # Seed a succeeded payment far outside even the 30d window.
    order_id = str(uuid.uuid4())
    db_session.add(
        Order(
            id=order_id,
            user_id=None,
            guest_email="guest-old@example.com",
            status="pending_payment",
            currency="USD",
            total_usd=Decimal("5.00"),
            total_charged=Decimal("5.00"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db_session.flush()
    db_session.add(
        Payment(
            id=str(uuid.uuid4()),
            order_id=order_id,
            provider="uzum",
            status="succeeded",
            amount=Decimal("5.00"),
            currency="USD",
            created_at=old,
            updated_at=old,
        )
    )
    await db_session.commit()

    r = await integration_client.get(
        "/api/v1/admin/payments/providers/uzum?window=30d",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["volume"] == []
    assert body["success_rate"]["succeeded"] == 0
    # recent is not window-scoped — it always shows the latest payments.
    assert len(body["recent"]) == 1
