"""Manual settlement of a payment whose provider webhook never arrived.

The acquirer took the customer's money but the callback was lost, so the order
sits in ``pending_payment`` forever. This is the operator's escape hatch — and
the single most dangerous admin action in the panel, because it asserts "money
arrived" without a provider actually saying so, and that assertion starts
fulfilment (real goods, real supplier balance). The guards below are the point.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import pytest

import yupay.api.v1  # noqa: F401  isort: skip  # resolve module import order

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
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


async def _admin_headers(client: AsyncClient, db: AsyncSession, *, tg_id: int) -> dict[str, str]:
    fields = {
        "user": json.dumps({"id": tg_id, "first_name": "A"}, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    data = "\n".join(f"{k}={v}" for k, v in sorted(fields.items())).encode()
    secret = hmac.new(b"WebAppData", b"123456:TEST", hashlib.sha256).digest()
    init = urlencode({**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()})
    login = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert login.status_code == 200, login.text
    uid = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == uid).values(roles=["admin"]))
    await db.commit()
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
async def _sku(db_session: AsyncSession) -> str:
    from yupay.core.ids import new_id
    from yupay.modules.sourcing.models import SkuSourcingRule

    category = Category(
        id=new_id(),
        slug="games-settle",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="cs2-settle",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="CS2")],
    )
    product = Product(
        id=new_id(),
        slug="cs2-settle",
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
        sku_code="cs2-settle-100",
        denomination="100",
        region="GLOBAL",
        price_usd=Decimal("0.99"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    db_session.add(SkuSourcingRule(sku_id=sku.id, mode="force_supplier", supplier_slug="mock"))
    await db_session.commit()
    return sku.id


async def _pending_payment(client: AsyncClient, token: str, sku_id: str, tag: str) -> str:
    """Create an order + intent, leave it unpaid. Returns the payment id."""
    order = await client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": f"settle-order-{tag}-padpadpad",
        },
        json={
            "currency": "USD",
            "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}],
        },
    )
    assert order.status_code == 201, order.text
    intent = await client.post(
        "/api/v1/payments/intents",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": f"settle-intent-{tag}-padpadpad",
        },
        json={"order_id": order.json()["id"], "provider": "mock"},
    )
    assert intent.status_code == 201, intent.text
    return intent.json()["id"]


async def test_admin_settle_requires_evidence_and_settles_once(
    integration_client: AsyncClient, db_session: AsyncSession, _sku: str
) -> None:
    user_token = (await _admin_headers(integration_client, db_session, tg_id=9101))[
        "Authorization"
    ].removeprefix("Bearer ")
    admin_h = await _admin_headers(integration_client, db_session, tg_id=9102)
    payment_id = await _pending_payment(integration_client, user_token, _sku, "a")

    idem = {"Idempotency-Key": "settle-key-aaaaaaaaaaaa"}

    # An Idempotency-Key is mandatory on this money path.
    no_key = await integration_client.post(
        f"/api/v1/admin/payments/{payment_id}/settle",
        headers=admin_h,
        json={"reason": "webhook lost", "provider_reference": "PAYME-12345"},
    )
    assert no_key.status_code == 422, no_key.text

    # Evidence is mandatory: an operator must have seen the provider's console.
    no_ref = await integration_client.post(
        f"/api/v1/admin/payments/{payment_id}/settle",
        headers={**admin_h, **idem},
        json={"reason": "webhook lost", "provider_reference": "  "},
    )
    assert no_ref.status_code == 422, no_ref.text

    ok = await integration_client.post(
        f"/api/v1/admin/payments/{payment_id}/settle",
        headers={**admin_h, **idem},
        json={"reason": "Click списал, вебхук не дошёл", "provider_reference": "CLICK-99887"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "succeeded"

    # The order moved to paid and the audit says a human did it, with evidence.
    order_id = ok.json()["order_id"]
    detail = await integration_client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_h)
    assert detail.status_code == 200, detail.text
    events = detail.json()["events"]
    settle_ev = next(e for e in events if e["kind"] == "admin.payment_settled")
    assert settle_ev["payload"]["provider_reference"] == "CLICK-99887"
    assert settle_ev["actor"].startswith("admin:")
    assert detail.json()["status"] in ("paid", "fulfilling", "fulfilled", "delivered")

    # Already settled — repeating is refused rather than double-crediting.
    again = await integration_client.post(
        f"/api/v1/admin/payments/{payment_id}/settle",
        headers={**admin_h, "Idempotency-Key": "settle-key-bbbbbbbbbbbb"},
        json={"reason": "again", "provider_reference": "CLICK-99887"},
    )
    assert again.status_code == 409, again.text
