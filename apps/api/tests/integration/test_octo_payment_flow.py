"""End-to-end payment through Octo.

Order → ``POST /payments/intents {provider: octo}`` → ``OctoGateway`` calls the
mocked Octo ``/prepare_payment`` → payment ``pending`` with ``octo_pay_url``.
A signed webhook on the generic ``/webhooks/payments/octo`` flips the payment to
``succeeded`` and the order to ``paid → delivered`` (mock supplier). Also covers
webhook replay (duplicate) and a bad signature (422).
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
)
from yupay.modules.payments.gateways.octo import compute_signature
from yupay.modules.sourcing.models import SkuSourcingRule

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
OCTO_BASE = "https://octo.test"
SIGNATURE_KEY = "octo-unique-key-test"


@pytest.fixture(autouse=True)
def _octo_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OCTO_SHOP_ID", "123")
    monkeypatch.setenv("OCTO_SECRET", "shop-secret")
    monkeypatch.setenv("OCTO_SIGNATURE_KEY", SIGNATURE_KEY)
    monkeypatch.setenv("OCTO_BASE_URL", OCTO_BASE)
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
    # Pin fulfilment to the mock supplier so paid → delivered happens synchronously.
    db_session.add(SkuSourcingRule(sku_id=sku.id, mode="force_supplier", supplier_slug="mock"))
    await db_session.commit()
    return sku.id


async def _create_order(client: AsyncClient, *, token: str, sku_id: str, key: str) -> str:
    r = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={"currency": "USD", "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _mock_prepare(uuid: str) -> None:
    respx.post(f"{OCTO_BASE}/prepare_payment").mock(
        return_value=httpx.Response(
            200,
            json={
                "error": 0,
                "data": {
                    "octo_payment_UUID": uuid,
                    "octo_pay_url": f"https://pay.octo.test/{uuid}",
                    "status": "created",
                },
            },
        )
    )


def _signed_webhook_body(uuid: str, status: str) -> str:
    return json.dumps(
        {
            "octo_payment_UUID": uuid,
            "shop_transaction_id": "tx",
            "status": status,
            # Octo sends the signature UPPERCASE; the gateway compares case-insensitively.
            "signature": compute_signature(SIGNATURE_KEY, uuid, status).upper(),
            "total_sum": 1.5,
        }
    )


async def test_octo_appears_in_providers(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/payments/providers")
    assert r.status_code == 200
    assert "octo" in r.json()["providers"]


@respx.mock
async def test_octo_happy_path_to_delivered(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    uuid = "octo-uuid-happy"
    _mock_prepare(uuid)

    token = await _login_user(integration_client, tg_id=701)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="octo-happy-aaaa-pad"
    )
    intent = await integration_client.post(
        "/api/v1/payments/intents",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "ik-octo-payment-flow-01-padpadpad",
        },
        json={"order_id": order_id, "provider": "octo"},
    )
    assert intent.status_code == 201, intent.text
    body = intent.json()
    assert body["provider"] == "octo"
    assert body["status"] == "pending"
    assert body["external_id"] == uuid
    assert body["intent_url"] == f"https://pay.octo.test/{uuid}"

    wh = await integration_client.post(
        "/api/v1/webhooks/payments/octo",
        content=_signed_webhook_body(uuid, "succeeded"),
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
async def test_octo_webhook_replay_is_idempotent(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    uuid = "octo-uuid-replay"
    _mock_prepare(uuid)
    token = await _login_user(integration_client, tg_id=702)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="octo-replay-bbbb-pad"
    )
    await integration_client.post(
        "/api/v1/payments/intents",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "ik-octo-payment-flow-02-padpadpad",
        },
        json={"order_id": order_id, "provider": "octo"},
    )
    payload = _signed_webhook_body(uuid, "succeeded")
    first = await integration_client.post(
        "/api/v1/webhooks/payments/octo",
        content=payload,
        headers={"content-type": "application/json"},
    )
    second = await integration_client.post(
        "/api/v1/webhooks/payments/octo",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate"}


@respx.mock
async def test_octo_webhook_bad_signature_rejected(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    uuid = "octo-uuid-badsig"
    _mock_prepare(uuid)
    token = await _login_user(integration_client, tg_id=703)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="octo-badsig-cccc-pad"
    )
    await integration_client.post(
        "/api/v1/payments/intents",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "ik-octo-payment-flow-03-padpadpad",
        },
        json={"order_id": order_id, "provider": "octo"},
    )
    bad = json.dumps({"octo_payment_UUID": uuid, "status": "succeeded", "signature": "deadbeef"})
    wh = await integration_client.post(
        "/api/v1/webhooks/payments/octo",
        content=bad,
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 422, wh.text
