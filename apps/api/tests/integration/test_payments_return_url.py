"""Acquirer ``return_url`` resolution: default to the web storefront, reject
cross-origin values.

Before this test existed, ``payments.service.create_intent`` defaulted a
missing ``return_url`` to a hardcoded ``https://app.yupay.uz/checkout/return``
and Octo additionally fell back to ``telegram_miniapp_url`` — neither of
which is the web order page, so customers landed on the wrong page after
paying. ``_safe_return_url`` now defaults to ``web_base_url`` (falling back
to ``base_url``) and rejects any client-supplied URL that isn't same-origin,
closing an open-redirect vector.

Covers:
- no ``return_url`` -> intent is created with a URL under ``web_base_url``
  (proven by inspecting what the Octo adapter actually sent upstream).
- a foreign-origin ``return_url`` -> 422 ``ValidationError``.
- a same-origin ``return_url`` -> forwarded to the acquirer verbatim.
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
from yupay.modules.sourcing.models import SkuSourcingRule

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
OCTO_BASE = "https://octo.test"
SIGNATURE_KEY = "octo-unique-key-test"
WEB_BASE = "https://storefront.test"


@pytest.fixture(autouse=True)
def _payments_env(monkeypatch: pytest.MonkeyPatch):
    """Real acquirer creds (so ``octo`` is ``available``) plus a distinct,
    explicit ``WEB_BASE_URL`` so origin assertions don't ride on whatever
    ``base_url`` happens to default to."""
    monkeypatch.setenv("OCTO_SHOP_ID", "123")
    monkeypatch.setenv("OCTO_SECRET", "shop-secret")
    monkeypatch.setenv("OCTO_SIGNATURE_KEY", SIGNATURE_KEY)
    monkeypatch.setenv("OCTO_BASE_URL", OCTO_BASE)
    monkeypatch.setenv("WEB_BASE_URL", WEB_BASE)
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
    # Pin fulfilment to the mock supplier so the order stays in
    # pending_payment (never auto-advances) for the intent calls below.
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


def _mock_prepare(uuid: str) -> respx.Route:
    return respx.post(f"{OCTO_BASE}/prepare_payment").mock(
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


@respx.mock
async def test_no_return_url_defaults_under_web_base_url(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    """No client-supplied return_url -> the acquirer receives a URL rooted at
    web_base_url, not the old hardcoded app.yupay.uz/checkout/return."""
    route = _mock_prepare("octo-uuid-default")
    token = await _login_user(integration_client, tg_id=901)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="return-url-default-pad"
    )
    r = await integration_client.post(
        "/api/v1/payments/intents",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "ik-return-url-01-padpadpad",
        },
        json={"order_id": order_id, "provider": "octo"},
    )
    assert r.status_code == 201, r.text

    sent = json.loads(route.calls.last.request.content)
    assert sent["return_url"] == f"{WEB_BASE}/checkout/return"
    assert not sent["return_url"].startswith("https://app.yupay.uz")


async def test_foreign_origin_return_url_rejected(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    """A return_url on a foreign origin is an open-redirect attempt -> 422,
    and the payment is never created."""
    token = await _login_user(integration_client, tg_id=902)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="return-url-foreign-pad"
    )
    r = await integration_client.post(
        "/api/v1/payments/intents",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "ik-return-url-02-padpadpad",
        },
        json={
            "order_id": order_id,
            "provider": "mock",
            "return_url": "https://evil.example/x",
        },
    )
    assert r.status_code == 422, r.text
    assert "storefront origin" in r.json()["detail"]

    # No payment/intent should have been created for the rejected request.
    active = await integration_client.get(
        f"/api/v1/payments/by-order/{order_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert active.status_code == 404


@respx.mock
async def test_same_origin_return_url_forwarded_verbatim(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    """A client-supplied return_url on the storefront's own origin is
    accepted and forwarded to the acquirer unchanged."""
    route = _mock_prepare("octo-uuid-verbatim")
    token = await _login_user(integration_client, tg_id=903)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="return-url-verbatim-pad"
    )
    candidate = f"{WEB_BASE}/orders/{order_id}?paid=1"
    r = await integration_client.post(
        "/api/v1/payments/intents",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "ik-return-url-03-padpadpad",
        },
        json={"order_id": order_id, "provider": "octo", "return_url": candidate},
    )
    assert r.status_code == 201, r.text

    sent = json.loads(route.calls.last.request.content)
    assert sent["return_url"] == candidate
