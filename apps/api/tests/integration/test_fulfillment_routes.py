"""Integration tests for the fulfilment skeleton.

End-to-end flow:
- create order → pay via mock provider → webhook flips order to ``paid``
  → fulfillment auto-starts → mock supplier returns artifact → order
  reaches ``delivered`` and a ``deliveries`` row exists.

Also covers:
- owner-only access to ``/orders/{id}/deliveries``
- admin can list, retry, and cancel tasks
- retry of a succeeded task is rejected
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
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


async def _grant_admin(db: AsyncSession, tg_id: int) -> str:
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return user_id


@pytest.fixture
async def _seed_sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="games",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="cs2",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="CS2")],
    )
    product = Product(
        id=new_id(),
        slug="cs2-coins",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Coins")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="cs2-100",
        denomination="100",
        region="GLOBAL",
        price_usd=Decimal("0.99"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return sku.id


async def _pay_and_fulfill(
    client: AsyncClient, *, token: str, sku_id: str, key_suffix: str
) -> str:
    """Helper: create order, create intent, post webhook → returns order_id (paid+delivered)."""
    create = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"fulfill-{key_suffix}"},
        json={
            "currency": "USD",
            "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}],
        },
    )
    assert create.status_code == 201, create.text
    order_id = create.json()["id"]
    intent = await client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}"},
        json={"order_id": order_id, "provider": "mock"},
    )
    external_id = intent.json()["external_id"]
    wh = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {
                "event_id": f"evt_{key_suffix}",
                "payment_id": external_id,
                "outcome": "succeeded",
            }
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text
    return order_id


# ---------- happy path ----------


async def test_paid_order_walks_to_delivered(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=201)
    order_id = await _pay_and_fulfill(
        integration_client, token=token, sku_id=_seed_sku, key_suffix="happy-aaaa"
    )

    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "delivered"
    assert body["paid_at"] is not None
    assert body["delivered_at"] is not None

    deliveries = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deliveries.status_code == 200, deliveries.text
    items = deliveries.json()["items"]
    assert len(items) == 1
    assert items[0]["channel"] == "in_app"
    assert items[0]["artifact_kind"] == "voucher_code"
    assert items[0]["artifact"]["code"].startswith("MOCK-")


async def test_deliveries_owner_only(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    owner = await _login_user(integration_client, tg_id=211)
    stranger = await _login_user(integration_client, tg_id=212)
    order_id = await _pay_and_fulfill(
        integration_client, token=owner, sku_id=_seed_sku, key_suffix="owner-bbbb"
    )
    r = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Bearer {stranger}"},
    )
    assert r.status_code == 404


# ---------- admin ----------


async def test_admin_can_list_tasks(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    user = await _login_user(integration_client, tg_id=221)
    order_id = await _pay_and_fulfill(
        integration_client, token=user, sku_id=_seed_sku, key_suffix="admin-cccc"
    )
    admin = await _login_user(integration_client, tg_id=222)
    await _grant_admin(db_session, tg_id=222)

    r = await integration_client.get(
        "/api/v1/admin/fulfillment/tasks",
        headers={"Authorization": f"Bearer {admin}"},
        params={"order_id": order_id},
    )
    assert r.status_code == 200, r.text
    tasks = r.json()["items"]
    assert len(tasks) == 1
    assert tasks[0]["status"] == "succeeded"
    assert tasks[0]["supplier"] == "mock"
    assert tasks[0]["attempts_count"] >= 1


async def test_admin_retry_rejects_succeeded_task(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    user = await _login_user(integration_client, tg_id=231)
    order_id = await _pay_and_fulfill(
        integration_client, token=user, sku_id=_seed_sku, key_suffix="retry-dddd"
    )
    admin = await _login_user(integration_client, tg_id=232)
    await _grant_admin(db_session, tg_id=232)
    admin_headers = {"Authorization": f"Bearer {admin}"}

    listing = await integration_client.get(
        "/api/v1/admin/fulfillment/tasks",
        headers=admin_headers,
        params={"order_id": order_id},
    )
    task_id = listing.json()["items"][0]["id"]

    retry = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/retry",
        headers=admin_headers,
    )
    assert retry.status_code == 409


async def test_admin_cancel_rejects_succeeded_task(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    user = await _login_user(integration_client, tg_id=241)
    order_id = await _pay_and_fulfill(
        integration_client, token=user, sku_id=_seed_sku, key_suffix="cancel-eeee"
    )
    admin = await _login_user(integration_client, tg_id=242)
    await _grant_admin(db_session, tg_id=242)
    admin_headers = {"Authorization": f"Bearer {admin}"}

    task_id = (
        await integration_client.get(
            "/api/v1/admin/fulfillment/tasks",
            headers=admin_headers,
            params={"order_id": order_id},
        )
    ).json()["items"][0]["id"]

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/cancel",
        headers=admin_headers,
    )
    assert r.status_code == 409


async def test_admin_required_for_fulfillment_admin(
    integration_client: AsyncClient,
) -> None:
    user = await _login_user(integration_client, tg_id=251)
    r = await integration_client.get(
        "/api/v1/admin/fulfillment/tasks",
        headers={"Authorization": f"Bearer {user}"},
    )
    assert r.status_code == 403
