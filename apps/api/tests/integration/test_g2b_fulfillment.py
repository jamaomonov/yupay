"""End-to-end fulfilment through G2B.

Paid order → sourcing routes to ``g2b`` → ``G2bFulfiller`` calls the
mocked G2B HTTP API → ``FulfillmentTask`` flips to ``succeeded`` and the
voucher codes land in ``Delivery.artifact``. Also covers the PENDING +
webhook reconciliation path.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
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
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
G2B_BASE = "https://g2b.test/v1"
WEBHOOK_SECRET = "wh-secret-test"


@pytest.fixture(autouse=True)
def _g2b_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("G2B_API_KEY", "test-key")
    monkeypatch.setenv("G2B_BASE_URL", G2B_BASE)
    monkeypatch.setenv("G2B_WEBHOOK_SECRET", WEBHOOK_SECRET)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


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


async def _seed_voucher_sku(db: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="vouchers",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Ваучеры")],
    )
    brand = Brand(
        id=new_id(),
        slug="g2b-test",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="G2B")],
    )
    product = Product(
        id=new_id(),
        slug="g2b-voucher",
        brand_id=brand.id,
        kind="voucher",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="G2B voucher")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="g2b-test-10",
        denomination="10",
        region="WW",
        price_usd=Decimal("1.00"),
        sort_order=10,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.commit()
    return sku.id


async def _seed_game_sku(db: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="games",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="pubg",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="PUBG")],
    )
    product = Product(
        id=new_id(),
        slug="pubg-uc",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[{"key": "player_id", "label": "Player ID", "type": "text"}],
        translations=[ProductTranslation(locale="ru", name="PUBG UC")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="pubg-60uc",
        denomination="60",
        region="WW",
        price_usd=Decimal("1.00"),
        sort_order=10,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.commit()
    return sku.id


async def _set_g2b_force(client: AsyncClient, *, token: str, sku_id: str) -> None:
    r = await client.put(
        f"/api/v1/admin/sourcing/rules/{sku_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"mode": "force_supplier", "supplier_slug": "g2b"},
    )
    assert r.status_code == 200, r.text


async def _create_mapping(
    db: AsyncSession,
    *,
    sku_id: str,
    kind: str,
    external_product_id: str,
    external_variant_id: str | None = None,
) -> None:
    db.add(
        SkuSupplierMapping(
            sku_id=sku_id,
            supplier_slug="g2b",
            kind=kind,
            external_product_id=external_product_id,
            external_variant_id=external_variant_id,
            quantity=1,
            extra={},
            is_active=True,
        )
    )
    await db.commit()


async def _pay_order(
    client: AsyncClient,
    *,
    token: str,
    sku_id: str,
    key_suffix: str,
    fulfillment_data: dict[str, str] | None = None,
) -> str:
    create = await client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": f"g2b-test-{key_suffix}",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": sku_id,
                    "qty": 1,
                    "fulfillment_data": fulfillment_data or {},
                }
            ],
        },
    )
    assert create.status_code == 201, create.text
    order_id = create.json()["id"]
    intent = await client.post(
        "/api/v1/payments/intents",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "ik-g2b-fulfillment-01-padpadpad",
        },
        json={"order_id": order_id, "provider": "mock"},
    )
    assert intent.status_code in (200, 201), intent.text
    external_id = intent.json()["external_id"]
    wh = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {
                "event_id": f"evt_g2b_{key_suffix}",
                "payment_id": external_id,
                "outcome": "succeeded",
            }
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text
    return order_id


# ---------- happy path: voucher COMPLETED ----------


@respx.mock
async def test_voucher_completed_delivers_codes(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_voucher_sku(db_session)
    admin = await _login_user(integration_client, tg_id=501)
    await _grant_admin(db_session, tg_id=501)
    await _set_g2b_force(integration_client, token=admin, sku_id=sku_id)
    await _create_mapping(db_session, sku_id=sku_id, kind="voucher", external_product_id="42")

    purchase = respx.post(f"{G2B_BASE}/products/42/purchase").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "order_id": 7777,
                "status": "COMPLETED",
                "delivery_items": ["G2B-CODE-1"],
            },
        )
    )

    customer = await _login_user(integration_client, tg_id=502)
    order_id = await _pay_order(
        integration_client, token=customer, sku_id=sku_id, key_suffix="voucher-ok"
    )

    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {customer}"},
    )
    assert detail.json()["status"] == "delivered", detail.json()

    deliveries = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Bearer {customer}"},
    )
    items = deliveries.json()["items"]
    assert len(items) == 1
    assert items[0]["artifact"]["code"] == "G2B-CODE-1"
    # source/external_order_id are internal audit fields; the customer API
    # strips them via the artifact allow-list
    # (fulfillment.service.BUYER_SAFE_ARTIFACT_KEYS) — only ``code``/``codes``
    # are buyer-safe here.
    assert "source" not in items[0]["artifact"]
    assert "external_order_id" not in items[0]["artifact"]
    assert purchase.called
    # Idempotency-Key must be the task.id (UUID) — it's the only thing
    # G2B knows about for replay safety.
    assert purchase.calls.last.request.headers.get("X-Idempotency-Key")


# ---------- async voucher: PENDING → webhook → succeeded ----------


@respx.mock
async def test_voucher_pending_then_webhook_completes(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_voucher_sku(db_session)
    admin = await _login_user(integration_client, tg_id=511)
    await _grant_admin(db_session, tg_id=511)
    await _set_g2b_force(integration_client, token=admin, sku_id=sku_id)
    await _create_mapping(db_session, sku_id=sku_id, kind="voucher", external_product_id="42")

    respx.post(f"{G2B_BASE}/products/42/purchase").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "order_id": 8888,
                "status": "PENDING",
                "delivery_items": None,
            },
        )
    )

    customer = await _login_user(integration_client, tg_id=512)
    order_id = await _pay_order(
        integration_client, token=customer, sku_id=sku_id, key_suffix="voucher-pending"
    )

    # After fulfill() the task should be in_progress, order in fulfilling.
    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {customer}"},
    )
    assert detail.json()["status"] == "fulfilling", detail.json()

    # Now the webhook arrives. The webhook handler re-fetches the order
    # status — we need a separate respx mock for the delivery endpoint.
    respx.get(f"{G2B_BASE}/orders/8888/delivery").mock(
        return_value=httpx.Response(200, json={"delivery_items": ["G2B-LATE"]})
    )

    wh = await integration_client.post(
        f"/api/v1/webhooks/g2b/{WEBHOOK_SECRET}",
        json={"order_id": 8888, "status": "COMPLETED"},
    )
    assert wh.status_code == 200
    assert wh.json()["task_status"] == "succeeded"

    deliveries = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Bearer {customer}"},
    )
    items = deliveries.json()["items"]
    assert len(items) == 1
    assert items[0]["artifact"]["code"] == "G2B-LATE"


# ---------- game order ----------


@respx.mock
async def test_game_pending_then_webhook_completes(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_game_sku(db_session)
    admin = await _login_user(integration_client, tg_id=521)
    await _grant_admin(db_session, tg_id=521)
    await _set_g2b_force(integration_client, token=admin, sku_id=sku_id)
    await _create_mapping(
        db_session,
        sku_id=sku_id,
        kind="game",
        external_product_id="pubg_mobile",
        external_variant_id="60 UC",
    )

    # The real G2B API wraps the order object under ``order`` (with a top-level
    # ``success``) — captured live from api.g2bulk.com. A flat mock here hid the
    # prod bug where ``external_order_id`` was persisted as "None" and the flat
    # webhook could never match it; keep this mock in the real shape so it stays
    # a regression guard.
    respx.post(f"{G2B_BASE}/games/pubg_mobile/order").mock(
        return_value=httpx.Response(
            200, json={"success": True, "order": {"order_id": 9090, "status": "PENDING"}}
        )
    )

    customer = await _login_user(integration_client, tg_id=522)
    order_id = await _pay_order(
        integration_client,
        token=customer,
        sku_id=sku_id,
        key_suffix="game-pending",
        fulfillment_data={"player_id": "5679523421"},
    )

    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {customer}"},
    )
    assert detail.json()["status"] == "fulfilling"

    # Status re-verification response is wrapped the same way as create.
    respx.post(f"{G2B_BASE}/games/order/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "order": {"order_id": 9090, "status": "COMPLETED", "message": "done"},
            },
        )
    )

    # The webhook body itself IS flat (top-level order_id) — that half of the
    # G2B contract is not wrapped, which is exactly why the receiver reads it
    # off the top level.
    wh = await integration_client.post(
        f"/api/v1/webhooks/g2b/{WEBHOOK_SECRET}",
        json={"order_id": 9090, "status": "COMPLETED"},
    )
    assert wh.status_code == 200
    assert wh.json()["task_status"] == "succeeded"

    deliveries = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Bearer {customer}"},
    )
    items = deliveries.json()["items"]
    assert len(items) == 1
    assert items[0]["artifact_kind"] == "topup_receipt"
    # external_order_id is an internal audit field, stripped by the artifact
    # allow-list ``fulfillment.service.BUYER_SAFE_ARTIFACT_KEYS``. The
    # human-readable message is the only buyer-safe field on a game top-up
    # receipt.
    assert "external_order_id" not in items[0]["artifact"]
    assert items[0]["artifact"]["message"] == "done"


# ---------- webhook security ----------


async def test_webhook_wrong_secret_returns_404(
    integration_client: AsyncClient,
) -> None:
    r = await integration_client.post(
        "/api/v1/webhooks/g2b/wrong-secret",
        json={"order_id": 1},
    )
    assert r.status_code == 404


async def test_webhook_unknown_order_does_not_500(
    integration_client: AsyncClient,
) -> None:
    r = await integration_client.post(
        f"/api/v1/webhooks/g2b/{WEBHOOK_SECRET}",
        json={"order_id": 99999999},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "unknown_order"


# ---------- missing mapping ----------


@respx.mock
async def test_attempts_endpoint_filters_by_supplier(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Admin can pull a G2B-only feed of attempts for the integrations
    detail page."""
    sku_id = await _seed_voucher_sku(db_session)
    admin = await _login_user(integration_client, tg_id=541)
    await _grant_admin(db_session, tg_id=541)
    await _set_g2b_force(integration_client, token=admin, sku_id=sku_id)
    await _create_mapping(db_session, sku_id=sku_id, kind="voucher", external_product_id="42")

    respx.post(f"{G2B_BASE}/products/42/purchase").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "order_id": 1234,
                "status": "COMPLETED",
                "delivery_items": ["X"],
            },
        )
    )

    customer = await _login_user(integration_client, tg_id=542)
    await _pay_order(
        integration_client,
        token=customer,
        sku_id=sku_id,
        key_suffix="attempts-feed",
    )

    feed = await integration_client.get(
        "/api/v1/admin/fulfillment/attempts?supplier=g2b&limit=10",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert feed.status_code == 200, feed.text
    body = feed.json()
    assert body["total"] >= 1
    assert all(item["supplier"] == "g2b" for item in body["items"])
    assert body["items"][0]["kind"] == "fulfill"
    assert body["items"][0]["status"] == "ok"


@respx.mock
async def test_missing_mapping_fails_task(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_voucher_sku(db_session)
    admin = await _login_user(integration_client, tg_id=531)
    await _grant_admin(db_session, tg_id=531)
    await _set_g2b_force(integration_client, token=admin, sku_id=sku_id)
    # NO mapping created.

    customer = await _login_user(integration_client, tg_id=532)
    order_id = await _pay_order(
        integration_client, token=customer, sku_id=sku_id, key_suffix="no-mapping-here"
    )

    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {customer}"},
    )
    assert detail.json()["status"] != "delivered"

    # Task is failed with a clear error.
    task = (
        await db_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()
    assert task.status == "failed"
    assert "mapping" in (task.last_error or "").lower()
