"""Manual-queue fulfilment: admin complete/fail/cancel guards and list filters.

A SKU without a sourcing rule lands in the manual queue (supplier="manual",
in_progress) — these tests walk the admin paths that were previously
uncovered: happy completion, the duplicate-delivery savepoint, validation
guards, rejection, cancellation, and the admin list filters.
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
from yupay.modules.fulfillment.models import Delivery
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


@pytest.fixture
async def _manual_sku(db_session: AsyncSession) -> str:
    """A SKU with NO sourcing rule — fulfilment routes it to the manual queue."""
    category = Category(
        id=new_id(),
        slug="giftcards",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Карты")],
    )
    brand = Brand(
        id=new_id(),
        slug="itunes",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="iTunes")],
    )
    product = Product(
        id=new_id(),
        slug="itunes-card",
        brand_id=brand.id,
        # top_up + no sourcing rule + no supplier mapping ⇒ manual queue
        # (vouchers would route to the inventory/mock path instead).
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Gift card")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="itunes-10",
        denomination="10",
        region="US",
        price_usd=Decimal("10.00"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return sku.id


async def _paid_manual_task(
    client: AsyncClient, *, token: str, sku_id: str, tag: str
) -> tuple[str, str]:
    """Order + mock payment + webhook → returns (order_id, manual task id)."""
    r = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"mf-order-{tag}-pad"},
        json={"currency": "USD", "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}]},
    )
    assert r.status_code == 201, r.text
    order_id = r.json()["id"]
    r = await client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"mf-intent-{tag}-pad"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert r.status_code == 201, r.text
    wh = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {"event_id": f"mf_{tag}", "payment_id": r.json()["external_id"], "outcome": "succeeded"}
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text

    tasks = await client.get(
        f"/api/v1/admin/fulfillment/tasks?order_id={order_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert tasks.status_code == 200, tasks.text
    items = tasks.json()["items"]
    assert len(items) == 1, items
    assert items[0]["supplier"] == "manual"
    assert items[0]["status"] == "in_progress"
    return order_id, items[0]["id"]


ARTIFACT = {"artifact_kind": "voucher_code", "artifact": {"code": "GIFT-1234"}}


async def test_manual_complete_delivers_order(
    integration_client: AsyncClient, db_session: AsyncSession, _manual_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=901)
    await _grant_admin(db_session, tg_id=901)
    headers = {"Authorization": f"Bearer {token}"}
    order_id, task_id = await _paid_manual_task(
        integration_client, token=token, sku_id=_manual_sku, tag="901"
    )

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/complete",
        headers=headers,
        json={**ARTIFACT, "admin_note": "delivered by hand", "proof_url": "https://x/proof.png"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "succeeded"

    order = await integration_client.get(f"/api/v1/orders/{order_id}", headers=headers)
    assert order.json()["status"] == "delivered"

    # Completing again is refused — the task already terminated.
    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/complete", headers=headers, json=ARTIFACT
    )
    assert r.status_code == 409, r.text


async def test_manual_complete_duplicate_delivery_conflicts(
    integration_client: AsyncClient, db_session: AsyncSession, _manual_sku: str
) -> None:
    """UNIQUE(order_item_id) on deliveries is the last line of defence — a
    pre-existing delivery turns the completion into a clean 409."""
    token = await _login_user(integration_client, tg_id=902)
    await _grant_admin(db_session, tg_id=902)
    order_id, task_id = await _paid_manual_task(
        integration_client, token=token, sku_id=_manual_sku, tag="902"
    )

    task = await integration_client.get(
        f"/api/v1/admin/fulfillment/tasks/{task_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    order_item_id = task.json()["order_item_id"]
    db_session.add(
        Delivery(
            id=new_id(),
            order_item_id=order_item_id,
            channel="in_app",
            artifact_kind="voucher_code",
            artifact={"code": "ALREADY-THERE"},
        )
    )
    await db_session.commit()

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/complete",
        headers={"Authorization": f"Bearer {token}"},
        json=ARTIFACT,
    )
    assert r.status_code == 409, r.text
    assert "delivery" in r.json()["detail"]


async def test_manual_complete_service_level_validation(
    integration_client: AsyncClient, db_session: AsyncSession, _manual_sku: str
) -> None:
    """The pydantic schema already blocks bad kinds/channels at the route, but
    the service guards must hold for direct callers too."""
    import yupay.api.v1  # noqa: F401  isort: skip  -- break the import cycle

    from yupay.core.errors import ValidationError
    from yupay.modules.fulfillment import service as svc

    token = await _login_user(integration_client, tg_id=903)
    await _grant_admin(db_session, tg_id=903)
    _, task_id = await _paid_manual_task(
        integration_client, token=token, sku_id=_manual_sku, tag="903"
    )

    with pytest.raises(ValidationError, match="artifact_kind"):
        await svc.complete_manual_task(
            db_session,
            task_id=task_id,
            artifact_kind="weird",
            artifact={"a": 1},
            channel=None,
            admin_note=None,
            admin_id="a1",
        )
    with pytest.raises(ValidationError, match="channel"):
        await svc.complete_manual_task(
            db_session,
            task_id=task_id,
            artifact_kind="voucher_code",
            artifact={"a": 1},
            channel="postal-pigeon",
            admin_note=None,
            admin_id="a1",
        )
    with pytest.raises(ValidationError, match="artifact"):
        await svc.complete_manual_task(
            db_session,
            task_id=task_id,
            artifact_kind="voucher_code",
            artifact={},
            channel=None,
            admin_note=None,
            admin_id="a1",
        )


async def test_manual_fail_and_guards(
    integration_client: AsyncClient, db_session: AsyncSession, _manual_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=904)
    await _grant_admin(db_session, tg_id=904)
    headers = {"Authorization": f"Bearer {token}"}
    _, task_id = await _paid_manual_task(
        integration_client, token=token, sku_id=_manual_sku, tag="904"
    )

    # Whitespace-only reason passes the schema (min_length=1) but not the service.
    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/fail", headers=headers, json={"reason": "  "}
    )
    assert r.status_code == 422, r.text

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/fail",
        headers=headers,
        json={"reason": "supplier out of stock", "admin_note": "told customer"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "failed"
    assert r.json()["last_error"] == "supplier out of stock"

    # Failing a task that is no longer in_progress is refused.
    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/fail",
        headers=headers,
        json={"reason": "again"},
    )
    assert r.status_code == 409, r.text


async def test_manual_cancel_task(
    integration_client: AsyncClient, db_session: AsyncSession, _manual_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=905)
    await _grant_admin(db_session, tg_id=905)
    headers = {"Authorization": f"Bearer {token}"}
    _, task_id = await _paid_manual_task(
        integration_client, token=token, sku_id=_manual_sku, tag="905"
    )

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/cancel", headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"

    # Cancelling a terminated task is refused.
    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/cancel", headers=headers
    )
    assert r.status_code == 409, r.text


async def test_admin_task_and_attempt_list_filters(
    integration_client: AsyncClient, db_session: AsyncSession, _manual_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=906)
    await _grant_admin(db_session, tg_id=906)
    headers = {"Authorization": f"Bearer {token}"}
    _, task_id = await _paid_manual_task(
        integration_client, token=token, sku_id=_manual_sku, tag="906"
    )

    r = await integration_client.get(
        "/api/v1/admin/fulfillment/tasks?supplier=manual&status_filter=in_progress",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert task_id in [t["id"] for t in r.json()["items"]]

    r = await integration_client.get(
        "/api/v1/admin/fulfillment/tasks?supplier=nope&status_filter=failed", headers=headers
    )
    assert r.status_code == 200
    assert r.json()["total"] == 0

    r = await integration_client.get(
        "/api/v1/admin/fulfillment/attempts?supplier=manual&status_filter=error", headers=headers
    )
    assert r.status_code == 200, r.text
