"""Integration tests for admin bulk operations on fulfillment tasks.

Covers POST /admin/fulfillment/tasks/bulk-retry — selectively replays failed/
pending tasks while reporting which ones were skipped and why.
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
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import Order, OrderItem
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


async def _make_task(
    db: AsyncSession, *, status: str = "failed", supplier: str = "manual"
) -> str:
    """Build the catalog + order + item chain needed for an isolated test task."""
    slug = uuid.uuid4().hex[:8]
    user_id = str(uuid.uuid4())
    db.add(
        User(
            id=user_id,
            email=f"u-{slug}@example.com",
            locale="ru",
            display_currency="USD",
            roles=[],
        )
    )
    await db.flush()
    cat_id = str(uuid.uuid4())
    brand_id = str(uuid.uuid4())
    product_id = str(uuid.uuid4())
    sku_id = str(uuid.uuid4())
    order_id = str(uuid.uuid4())
    item_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    db.add(Category(id=cat_id, slug=f"c-{slug}"))
    await db.flush()
    db.add(Brand(id=brand_id, slug=f"b-{slug}", category_id=cat_id))
    await db.flush()
    db.add(Product(id=product_id, slug=f"p-{slug}", brand_id=brand_id, kind="top_up"))
    await db.flush()
    db.add(Sku(id=sku_id, product_id=product_id, sku_code=f"sku-{slug}", price_usd=Decimal("1.00")))
    await db.flush()
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            guest_email=None,
            status="paid",
            currency="USD",
            total_usd=Decimal("1.00"),
            total_charged=Decimal("1.00"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db.flush()
    db.add(
        OrderItem(
            id=item_id,
            order_id=order_id,
            sku_id=sku_id,
            qty=1,
            unit_price_usd=Decimal("1.00"),
        )
    )
    await db.flush()
    db.add(
        FulfillmentTask(
            id=task_id,
            order_id=order_id,
            order_item_id=item_id,
            supplier=supplier,
            status=status,
        )
    )
    await db.commit()
    return task_id


# ---------- auth gate ----------


async def test_bulk_retry_requires_token(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        "/api/v1/admin/fulfillment/tasks/bulk-retry",
        json={"task_ids": [str(uuid.uuid4())]},
    )
    assert r.status_code == 401


async def test_bulk_retry_forbids_non_admin(integration_client: AsyncClient) -> None:
    token = await _login(integration_client, tg_id=200)
    r = await integration_client.post(
        "/api/v1/admin/fulfillment/tasks/bulk-retry",
        json={"task_ids": [str(uuid.uuid4())]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


# ---------- happy path ----------


async def test_bulk_retry_replays_all_failed(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    t1 = await _make_task(db_session, status="failed")
    t2 = await _make_task(db_session, status="failed")
    r = await integration_client.post(
        "/api/v1/admin/fulfillment/tasks/bulk-retry",
        headers=_admin_headers,
        json={"task_ids": [t1, t2]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"retried", "skipped"}
    assert sorted(t["id"] for t in body["retried"]) == sorted([t1, t2])
    assert body["skipped"] == []


# ---------- mixed: some skipped ----------


async def test_bulk_retry_skips_non_retryable_tasks(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    retryable = await _make_task(db_session, status="failed")
    succeeded = await _make_task(db_session, status="succeeded")
    cancelled = await _make_task(db_session, status="cancelled")
    r = await integration_client.post(
        "/api/v1/admin/fulfillment/tasks/bulk-retry",
        headers=_admin_headers,
        json={"task_ids": [retryable, succeeded, cancelled]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [t["id"] for t in body["retried"]] == [retryable]
    skipped_ids = {s["id"] for s in body["skipped"]}
    assert skipped_ids == {succeeded, cancelled}
    for s in body["skipped"]:
        assert s["reason"]  # non-empty


async def test_bulk_retry_skips_unknown_task(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    missing = str(uuid.uuid4())
    r = await integration_client.post(
        "/api/v1/admin/fulfillment/tasks/bulk-retry",
        headers=_admin_headers,
        json={"task_ids": [missing]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["retried"] == []
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["id"] == missing


# ---------- input validation ----------


async def test_bulk_retry_rejects_empty_list(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    r = await integration_client.post(
        "/api/v1/admin/fulfillment/tasks/bulk-retry",
        headers=_admin_headers,
        json={"task_ids": []},
    )
    assert r.status_code == 422


async def test_bulk_retry_caps_batch_size(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    too_many = [str(uuid.uuid4()) for _ in range(101)]
    r = await integration_client.post(
        "/api/v1/admin/fulfillment/tasks/bulk-retry",
        headers=_admin_headers,
        json={"task_ids": too_many},
    )
    assert r.status_code == 422
