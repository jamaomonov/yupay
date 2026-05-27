"""End-to-end ``supplier_low_balance`` flow.

Three checks live here:

1. Pre-flight ``getMe`` detects an underfunded G2B wallet → task lands
   in ``failed`` with ``last_error=supplier_low_balance``, but the
   order item stays ``in_progress`` (storefront keeps showing
   "в обработке").
2. A topped-up supplier + ``/admin/fulfillment/tasks/{id}/retry`` walks
   the task back to ``succeeded`` and produces a Delivery.
3. The admin force-complete endpoint accepts a low-balance task and
   lays down a manual artifact when ops decide to deliver by hand.

The Telegram alert side is covered by asserting the post against the
admin-bot URL — Redis dedupe is fakeredis here, real Redis would be
exercised separately.
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
ALERT_BOT_TOKEN = "alert-bot-low-bal"
ALERT_CHAT_ID = "777111"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("G2B_API_KEY", "test-key")
    monkeypatch.setenv("G2B_BASE_URL", G2B_BASE)
    monkeypatch.setenv("TG_ALERT_BOT_TOKEN", ALERT_BOT_TOKEN)
    monkeypatch.setenv("TG_ALERT_CHAT_ID", ALERT_CHAT_ID)
    cfg.get_settings.cache_clear()
    # Wipe the alert-dedupe key so a stale entry from a previous run
    # doesn't suppress the alert we're about to assert against. We
    # ignore errors — Redis is best-effort here too.
    try:
        import redis

        client = redis.from_url(cfg.get_settings().redis_url)
        client.delete("alert:low_balance:g2b")
        client.close()
    except Exception:  # noqa: BLE001
        pass
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
    assert r.status_code == 200
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


async def _seed_game_sku(db: AsyncSession, *, cost_usdt: str = "0.89") -> str:
    category = Category(
        id=new_id(),
        slug="cat-lb",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Cat")],
    )
    brand = Brand(
        id=new_id(),
        slug="br-lb",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Br")],
    )
    product = Product(
        id=new_id(),
        slug="prod-lb",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[{"key": "player_id", "label": "Player ID", "type": "text"}],
        translations=[ProductTranslation(locale="ru", name="Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="sk-lb",
        denomination="60",
        region="WW",
        price_usd=Decimal("1.00"),
        cost_usdt=Decimal(cost_usdt),
        sort_order=10,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.commit()
    return sku.id


async def _seed_mapping(
    db: AsyncSession,
    *,
    sku_id: str,
    game_code: str = "pubgm",
    denom: str = "60",
) -> None:
    db.add(
        SkuSupplierMapping(
            sku_id=sku_id,
            supplier_slug="g2b",
            kind="game",
            external_product_id=game_code,
            external_variant_id=denom,
            quantity=1,
            extra={},
            is_active=True,
        )
    )
    await db.commit()


async def _set_g2b_force(client: AsyncClient, *, token: str, sku_id: str) -> None:
    r = await client.put(
        f"/api/v1/admin/sourcing/rules/{sku_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"mode": "force_supplier", "supplier_slug": "g2b"},
    )
    assert r.status_code == 200, r.text


async def _pay_order(
    client: AsyncClient,
    *,
    token: str,
    sku_id: str,
    key_suffix: str,
) -> str:
    create = await client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": f"low-bal-test-{key_suffix}",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": sku_id,
                    "qty": 1,
                    "fulfillment_data": {"player_id": "5679523421"},
                }
            ],
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
                "event_id": f"evt_lb_{key_suffix}",
                "payment_id": external_id,
                "outcome": "succeeded",
            }
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text
    return order_id


# ---------- pre-flight check ----------


@respx.mock
async def test_low_balance_preflight_marks_task_failed_but_item_in_progress(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_game_sku(db_session, cost_usdt="5.00")
    admin = await _login_user(integration_client, tg_id=801)
    await _grant_admin(db_session, tg_id=801)
    await _set_g2b_force(integration_client, token=admin, sku_id=sku_id)
    await _seed_mapping(db_session, sku_id=sku_id)

    # G2B reports balance below the SKU's cost — purchase should NOT
    # be attempted.
    respx.get(f"{G2B_BASE}/getMe").mock(
        return_value=httpx.Response(200, json={"username": "u", "balance": 0.5})
    )
    purchase_route = respx.post(f"{G2B_BASE}/games/pubgm/order").mock(
        return_value=httpx.Response(200, json={"order_id": 1, "status": "PENDING"})
    )
    # Specific BEFORE catch-all — respx matches in registration order.
    alert_route = respx.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    # Catch-all so unrelated customer-bot calls don't break the test.
    respx.post(host="api.telegram.org").mock(
        return_value=httpx.Response(200, json={"ok": True}),
    )

    customer = await _login_user(integration_client, tg_id=802)
    order_id = await _pay_order(
        integration_client, token=customer, sku_id=sku_id, key_suffix="preflight"
    )

    # No purchase attempt should have hit G2B.
    assert purchase_route.call_count == 0
    # Alert fires (best-effort; Redis dedupe may swallow on re-runs).
    assert alert_route.called

    # Customer-facing state remains "fulfilling" / "in_progress".
    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {customer}"},
    )
    assert detail.json()["status"] == "fulfilling"

    # Admin-facing task is failed with the low-balance sentinel.
    task = (
        await db_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()
    assert task.status == "failed"
    assert task.last_error == "supplier_low_balance"
    assert task.extra_metadata.get("low_balance") is True


# ---------- retry after top-up ----------


@respx.mock
async def test_retry_after_top_up_walks_task_to_succeeded(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_game_sku(db_session, cost_usdt="5.00")
    admin = await _login_user(integration_client, tg_id=803)
    await _grant_admin(db_session, tg_id=803)
    await _set_g2b_force(integration_client, token=admin, sku_id=sku_id)
    await _seed_mapping(db_session, sku_id=sku_id)

    # First /getMe call — pre-flight on the original purchase. Empty.
    # Second /getMe call — pre-flight on the retry. Topped up.
    respx.get(f"{G2B_BASE}/getMe").mock(
        side_effect=[
            httpx.Response(200, json={"balance": 0.5}),
            httpx.Response(200, json={"balance": 50.0}),
        ]
    )
    respx.post(f"{G2B_BASE}/games/pubgm/order").mock(
        return_value=httpx.Response(200, json={"order_id": 42, "status": "COMPLETED"})
    )
    # Specific BEFORE catch-all — respx matches in registration order.
    respx.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    respx.post(host="api.telegram.org").mock(
        return_value=httpx.Response(200, json={"ok": True}),
    )

    customer = await _login_user(integration_client, tg_id=804)
    order_id = await _pay_order(
        integration_client, token=customer, sku_id=sku_id, key_suffix="retry-flow"
    )

    task = (
        await db_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()
    assert task.last_error == "supplier_low_balance"

    # Admin tops up and clicks "Retry".
    retry = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task.id}/retry",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert retry.status_code == 200, retry.text

    await db_session.refresh(task)
    assert task.status == "succeeded"

    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {customer}"},
    )
    assert detail.json()["status"] == "delivered"


# ---------- admin force complete ----------


@respx.mock
async def test_force_complete_accepts_g2b_low_balance_task(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_game_sku(db_session, cost_usdt="5.00")
    admin = await _login_user(integration_client, tg_id=805)
    await _grant_admin(db_session, tg_id=805)
    await _set_g2b_force(integration_client, token=admin, sku_id=sku_id)
    await _seed_mapping(db_session, sku_id=sku_id)

    respx.get(f"{G2B_BASE}/getMe").mock(return_value=httpx.Response(200, json={"balance": 0.5}))
    # Specific BEFORE catch-all — respx matches in registration order.
    respx.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    respx.post(host="api.telegram.org").mock(
        return_value=httpx.Response(200, json={"ok": True}),
    )

    customer = await _login_user(integration_client, tg_id=806)
    order_id = await _pay_order(
        integration_client, token=customer, sku_id=sku_id, key_suffix="force-comp"
    )
    task = (
        await db_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()
    assert task.status == "failed"

    # Admin delivers the code by hand off-platform.
    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task.id}/force-complete",
        headers={"Authorization": f"Bearer {admin}"},
        json={
            "artifact_kind": "topup_receipt",
            "artifact": {"manual_note": "выдано через G2B напрямую"},
            "channel": "in_app",
            "admin_note": "пополнили баланс вручную после жалобы клиента",
            "proof_url": "https://proof.example/abc",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "succeeded"

    # Audit marker is present.
    await db_session.refresh(task)
    assert task.extra_metadata.get("force_complete") is True

    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {customer}"},
    )
    assert detail.json()["status"] == "delivered"
