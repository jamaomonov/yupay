"""End-to-end payment through InPay.

Order (UZS) → ``POST /payments/intents {provider: inpay}`` → InpayGateway
authorizes, calls /create → payment ``pending`` with ``pay_url``. InPay's
unsigned callback on ``/webhooks/payments/inpay`` is re-verified via
/transactions before the payment flips to ``succeeded`` and the order to
``paid → delivered`` (mock supplier). Covers replay (duplicate) and a
non-terminal /transactions status (``pending`` → no-op).
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
    SkuPrice,
)
from yupay.modules.payments.gateways import REGISTRY
from yupay.modules.sourcing.models import SkuSourcingRule

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
INPAY_BASE = "https://inpay.test/api/v1"


@pytest.fixture(autouse=True)
def _inpay_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INPAY_MERCHANT_ID", "22715")
    monkeypatch.setenv("INPAY_MERCHANT_TOKEN", "tok-32")
    monkeypatch.setenv("INPAY_BASE_URL", INPAY_BASE)
    cfg.get_settings.cache_clear()
    # Reset the singleton gateway's cached bearer token so each test starts clean.
    gw = REGISTRY["inpay"]
    gw._bearer = None  # type: ignore[attr-defined]
    gw._bearer_exp = 0.0  # type: ignore[attr-defined]
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
        slug="dota",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Dota 2")],
    )
    product = Product(
        id=new_id(),
        slug="dota-points",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Dota Points")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="dota-100",
        denomination="100",
        region="GLOBAL",
        price_usd=Decimal("1.50"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    # UZS override → checkout skips FX (no live provider call in tests).
    db_session.add(SkuPrice(sku_id=sku.id, currency="UZS", price=Decimal("15000")))
    # Pin fulfilment to the mock supplier so paid → delivered is synchronous.
    db_session.add(SkuSourcingRule(sku_id=sku.id, mode="force_supplier", supplier_slug="mock"))
    await db_session.commit()
    return sku.id


async def _create_order(client: AsyncClient, *, token: str, sku_id: str, key: str) -> str:
    r = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={"currency": "UZS", "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _mock_authorize() -> None:
    respx.get(f"{INPAY_BASE}/authorization/").mock(
        return_value=httpx.Response(200, json={"success": True, "bearer_token": "BEARER-T"})
    )


def _mock_create(order_id: str) -> None:
    respx.post(f"{INPAY_BASE}/create/").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "order_id": order_id,
                "pay_url": f"https://inpay.test/checkout/{order_id}",
            },
        )
    )


def _mock_status(order_id: str, status: str) -> None:
    respx.get(f"{INPAY_BASE}/transactions/").mock(
        return_value=httpx.Response(
            200, json={"success": True, "order_id": order_id, "status": status}
        )
    )


async def test_inpay_appears_in_providers(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/payments/providers")
    assert r.status_code == 200
    assert "inpay" in r.json()["providers"]


@respx.mock
async def test_inpay_happy_path_to_delivered(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    inpay_order = "inpay-oid-happy"
    _mock_authorize()
    _mock_create(inpay_order)
    _mock_status(inpay_order, "success")

    token = await _login_user(integration_client, tg_id=801)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="inpay-happy-aaaa"
    )
    intent = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}"},
        json={"order_id": order_id, "provider": "inpay"},
    )
    assert intent.status_code == 201, intent.text
    body = intent.json()
    assert body["provider"] == "inpay"
    assert body["status"] == "pending"
    assert body["external_id"] == inpay_order
    assert body["intent_url"] == f"https://inpay.test/checkout/{inpay_order}"

    # InPay's unsigned callback — body says success, but we re-verify via /transactions.
    wh = await integration_client.post(
        "/api/v1/webhooks/payments/inpay",
        content=json.dumps({"order_id": inpay_order, "status": "success", "amount": "15000.00"}),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text
    assert wh.json()["status"] == "processed"

    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "delivered"


@respx.mock
async def test_inpay_webhook_replay_is_idempotent(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    inpay_order = "inpay-oid-replay"
    _mock_authorize()
    _mock_create(inpay_order)
    _mock_status(inpay_order, "success")
    token = await _login_user(integration_client, tg_id=802)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="inpay-replay-bbbb"
    )
    await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}"},
        json={"order_id": order_id, "provider": "inpay"},
    )
    payload = json.dumps({"order_id": inpay_order, "status": "success"})
    first = await integration_client.post(
        "/api/v1/webhooks/payments/inpay",
        content=payload,
        headers={"content-type": "application/json"},
    )
    second = await integration_client.post(
        "/api/v1/webhooks/payments/inpay",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate"}


@respx.mock
async def test_inpay_pending_status_is_noop(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    inpay_order = "inpay-oid-pending"
    _mock_authorize()
    _mock_create(inpay_order)
    _mock_status(inpay_order, "pending")  # /transactions still pending
    token = await _login_user(integration_client, tg_id=803)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="inpay-pending-cccc"
    )
    await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}"},
        json={"order_id": order_id, "provider": "inpay"},
    )
    wh = await integration_client.post(
        "/api/v1/webhooks/payments/inpay",
        content=json.dumps({"order_id": inpay_order, "status": "success"}),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text
    # Re-verify said pending → no FSM change; order stays awaiting payment.
    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert detail.json()["status"] == "pending_payment"
