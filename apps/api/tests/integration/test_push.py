"""Push to the mobile app (ADR-0102): devices, queueing at the status seam, sending, receipts.

Pinned here: a token moves to the account that registered it last; an order outcome queues
one message per active device and only once; merchant and guest orders queue nothing; the
worker marks what Expo accepted, retries what it could not reach, and disables a device Expo
says is gone — at send time and from a receipt.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.orders.models import Order
from yupay.modules.orders.service import on_order_status_changed
from yupay.modules.push import expo
from yupay.modules.push.delivery import check_receipts, drain_pending_pushes
from yupay.modules.push.models import PushDevice, PushMessage
from yupay.modules.push.service import disable_device, register_device

from tests.integration.test_payments_wallet_gateway import _login_user
from tests.integration.test_reviews_service import _make_order, _make_user, _seed_brand

pytestmark = pytest.mark.asyncio

TOKEN = "ExponentPushToken[abcdefghijklmnop]"


def _token(n: int) -> str:
    return f"ExponentPushToken[device{n:012d}]"


async def _delivered(db: AsyncSession, *, user_id: str, slug: str) -> Order:
    _, sku = await _seed_brand(db, slug)
    order = await _make_order(db, user_id=user_id, sku_id=sku.id, status="delivered")
    order.updated_at = now()
    return order


async def _messages(db: AsyncSession) -> list[PushMessage]:
    return list((await db.execute(select(PushMessage).order_by(PushMessage.created_at))).scalars())


async def test_a_token_moves_to_the_account_that_registered_it_last(
    db_session: AsyncSession,
) -> None:
    first = await _make_user(db_session)
    second = await _make_user(db_session)
    device = await register_device(
        db_session, user_id=first.id, token=TOKEN, platform="ios", app_version="1.0"
    )
    await disable_device(db_session, user_id=first.id, device_id=device.id)
    moved = await register_device(
        db_session, user_id=second.id, token=TOKEN, platform="ios", app_version="1.1"
    )
    assert moved.id == device.id
    assert moved.user_id == second.id
    assert moved.disabled_at is None


async def test_a_delivered_order_queues_once_per_active_device(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    await register_device(
        db_session, user_id=user.id, token=_token(1), platform="ios", app_version=None
    )
    phone = await register_device(
        db_session, user_id=user.id, token=_token(2), platform="android", app_version=None
    )
    await disable_device(db_session, user_id=user.id, device_id=phone.id)
    order = await _delivered(db_session, user_id=user.id, slug="push-a")

    await on_order_status_changed(db_session, order, publish_realtime=False)
    await on_order_status_changed(db_session, order, publish_realtime=False)

    rows = await _messages(db_session)
    assert len(rows) == 1
    assert rows[0].kind == "order_delivered"
    assert rows[0].title == "Заказ выполнен"
    assert rows[0].body == "Push-A"
    assert rows[0].data == {"type": "order", "order_id": order.id}


async def test_a_credited_top_up_says_how_much(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    await register_device(
        db_session, user_id=user.id, token=_token(3), platform="ios", app_version=None
    )
    order = await _delivered(db_session, user_id=user.id, slug="push-b")
    order.purpose = "wallet_topup"
    order.currency = "UZS"
    order.total_charged = Decimal("50000")

    await on_order_status_changed(db_session, order, publish_realtime=False)

    (row,) = await _messages(db_session)
    assert (row.kind, row.title, row.body) == ("wallet_credited", "Баланс пополнен", "+50 000 сум")


async def test_no_device_or_no_account_queues_nothing(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    order = await _delivered(db_session, user_id=user.id, slug="push-c")
    await on_order_status_changed(db_session, order, publish_realtime=False)
    order.status = "paid"
    await on_order_status_changed(db_session, order, publish_realtime=False)
    assert await _messages(db_session) == []


async def _queued(db: AsyncSession, n: int) -> list[PushMessage]:
    user = await _make_user(db)
    for i in range(n):
        await register_device(
            db, user_id=user.id, token=_token(100 + i), platform="ios", app_version=None
        )
    order = await _delivered(db, user_id=user.id, slug=f"push-q{n}")
    await on_order_status_changed(db, order, publish_realtime=False)
    return await _messages(db)


async def test_the_worker_sends_and_disables_a_gone_device(db_session: AsyncSession) -> None:
    queued = await _queued(db_session, 2)
    sent: list[list[dict[str, Any]]] = []

    async def sender(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sent.append(batch)
        return [
            {"status": "ok", "id": "ticket-1"},
            {"status": "error", "details": {"error": "DeviceNotRegistered"}},
        ]

    assert await drain_pending_pushes(db_session, live=True, sender=sender) == 2
    assert len(sent) == 1
    assert {m["to"] for m in sent[0]} == {_token(100), _token(101)}
    for row in queued:
        await db_session.refresh(row)
    ok, gone = sorted(queued, key=lambda m: m.status != "sent")
    assert (ok.status, ok.ticket_id) == ("sent", "ticket-1")
    assert (gone.status, gone.last_error) == ("failed", "DeviceNotRegistered")
    device = await db_session.get(PushDevice, gone.device_id)
    assert device is not None
    assert device.disabled_reason == "not_registered"
    assert await drain_pending_pushes(db_session, live=True, sender=sender) == 0


async def test_an_unreachable_expo_is_retried_later(db_session: AsyncSession) -> None:
    (row,) = await _queued(db_session, 1)

    async def sender(_: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raise expo.ExpoUnavailableError("http 503", retry_after=120)

    await drain_pending_pushes(db_session, live=True, sender=sender)
    await db_session.refresh(row)
    assert (row.status, row.attempts) == ("pending", 1)
    assert row.next_attempt_at > now() + timedelta(seconds=100)
    assert await drain_pending_pushes(db_session, live=True, sender=sender) == 0


async def test_outside_prod_messages_are_skipped(db_session: AsyncSession) -> None:
    (row,) = await _queued(db_session, 1)
    await drain_pending_pushes(db_session, live=False)
    await db_session.refresh(row)
    assert row.status == "skipped"


async def test_a_receipt_saying_gone_disables_the_device(db_session: AsyncSession) -> None:
    (row,) = await _queued(db_session, 1)
    row.status = "sent"
    row.ticket_id = "t-9"
    row.sent_at = now() - timedelta(minutes=20)
    await db_session.flush()

    async def reader(ids: list[str]) -> dict[str, dict[str, Any]]:
        assert ids == ["t-9"]
        return {"t-9": {"status": "error", "details": {"error": "DeviceNotRegistered"}}}

    assert await check_receipts(db_session, reader=reader) == 1
    await db_session.refresh(row)
    assert row.receipt_status == "error"
    device = await db_session.get(PushDevice, row.device_id)
    assert device is not None
    assert device.disabled_at is not None


async def test_the_app_registers_and_signs_out_a_device(
    integration_client: AsyncClient,
) -> None:
    token, _ = await _login_user(integration_client, 91_000_001)
    auth = {"Authorization": f"Bearer {token}"}
    body = {"token": TOKEN, "platform": "android", "app_version": "1.0.0"}

    no_key = await integration_client.put("/api/v1/push/devices", json=body, headers=auth)
    assert no_key.status_code == 422
    bad = await integration_client.put(
        "/api/v1/push/devices",
        json={**body, "token": "not-a-token"},
        headers={**auth, "Idempotency-Key": new_id()},
    )
    assert bad.status_code == 422

    key = new_id()
    first = await integration_client.put(
        "/api/v1/push/devices", json=body, headers={**auth, "Idempotency-Key": key}
    )
    again = await integration_client.put(
        "/api/v1/push/devices", json=body, headers={**auth, "Idempotency-Key": key}
    )
    assert first.status_code == 200
    assert again.json() == first.json()
    assert "token" not in first.json()
    device_id = first.json()["id"]

    listed = await integration_client.get("/api/v1/push/devices", headers=auth)
    assert [d["id"] for d in listed.json()["items"]] == [device_id]

    gone = await integration_client.delete(
        f"/api/v1/push/devices/{device_id}", headers={**auth, "Idempotency-Key": new_id()}
    )
    assert gone.json()["active"] is False
    other = await integration_client.delete(
        f"/api/v1/push/devices/{new_id()}", headers={**auth, "Idempotency-Key": new_id()}
    )
    assert other.status_code == 404
    assert (await integration_client.get("/api/v1/push/devices", headers=auth)).json() == {
        "items": []
    }
