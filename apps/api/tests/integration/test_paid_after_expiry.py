"""Money that lands after the order's TTL must not disappear.

An order lives ten minutes. ``expire_stale_orders`` (and the lazy read-path
guard) then flip it to ``expired`` and cancel our payment row — but nothing
cancels the transaction at the acquirer, and neither Click's ``/complete``,
Uzum's ``/confirm`` nor Payme's ``PerformTransaction`` re-checks the order
status before settling. A buyer who is slow with an SMS code really is
debited at minute eleven.

Until this was fixed the settlement chokepoint did its work inside
``if order.status == "pending_payment"``, so that payment silently became
``succeeded`` against an ``expired`` order: no credit, no fulfilment, and
invisible to the stuck-order watchdog, which keys on ``paid_at``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
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
from yupay.modules.orders.models import Order, OrderEvent

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


def _sign(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    return urlencode({**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()})


async def _login(client: AsyncClient, tg_id: int) -> str:
    init = _sign(
        {
            "user": json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":")),
            "auth_date": str(int(time.time())),
        }
    )
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


async def _expire(client: AsyncClient, db: AsyncSession, *, order_id: str, token: str) -> None:
    """Age the order past its TTL, then let the read-path guard flip it.

    Going through the guard rather than writing ``status`` by hand keeps the
    cascade that cancels the open payment row, which is the state the acquirer
    callback actually arrives into.
    """
    await db.execute(
        update(Order).where(Order.id == order_id).values(expires_at=now() - timedelta(minutes=1))
    )
    await db.commit()
    read = await client.get(
        f"/api/v1/orders/{order_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert read.status_code == 200, read.text
    assert read.json()["status"] == "expired", "precondition: the order must have expired"


async def _settle_mock(client: AsyncClient, *, external_id: str, tag: str) -> None:
    r = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {"event_id": f"evt-{tag}", "payment_id": external_id, "outcome": "succeeded"}
        ),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 200, r.text


# ---------- wallet top-up ----------


async def _topup(client: AsyncClient, *, token: str, amount: str, key: str) -> dict[str, object]:
    r = await client.post(
        "/api/v1/wallet/topup",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": key,
            "X-Yupay-Surface": "miniapp",
        },
        json={"amount": amount, "provider": "mock"},
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def _wallet_uzs(overview: dict[str, object]) -> Decimal:
    balances = overview["balances"]
    assert isinstance(balances, list)
    for row in balances:
        assert isinstance(row, dict)
        if row.get("kind") == "user_wallet" and row.get("currency") == "UZS":
            return Decimal(str(row["balance"]))
    return Decimal("0")


async def test_a_deposit_paid_after_expiry_is_still_credited(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The acquirer debited the customer, so the obligation exists."""
    token = await _login(integration_client, tg_id=9711)
    payment = await _topup(
        integration_client, token=token, amount="10000", key="late-topup-credit-1"
    )
    order_id = payment["order_id"]
    assert isinstance(order_id, str)
    external_id = payment["external_id"]
    assert isinstance(external_id, str)

    await _expire(integration_client, db_session, order_id=order_id, token=token)
    await _settle_mock(integration_client, external_id=external_id, tag="late-topup-1")

    wallet = await integration_client.get(
        "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
    )
    assert wallet.status_code == 200
    assert _wallet_uzs(wallet.json()) == Decimal("10000")

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    await db_session.refresh(order)
    assert order.status == "delivered"
    assert order.paid_at is not None


async def test_a_late_deposit_credits_only_once(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A retried callback must not pay the customer twice."""
    token = await _login(integration_client, tg_id=9712)
    payment = await _topup(
        integration_client, token=token, amount="10000", key="late-topup-credit-2"
    )
    external_id = payment["external_id"]
    assert isinstance(external_id, str)
    order_id = payment["order_id"]
    assert isinstance(order_id, str)

    await _expire(integration_client, db_session, order_id=order_id, token=token)
    await _settle_mock(integration_client, external_id=external_id, tag="late-topup-2a")
    await _settle_mock(integration_client, external_id=external_id, tag="late-topup-2b")

    wallet = await integration_client.get(
        "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
    )
    assert _wallet_uzs(wallet.json()) == Decimal("10000")


# ---------- catalogue order ----------


@pytest.fixture
async def _sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="late-cat",
        sort_order=1,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Late")],
    )
    brand = Brand(
        id=new_id(),
        category_id=category.id,
        slug="late-brand",
        sort_order=1,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Late Brand")],
    )
    product = Product(
        id=new_id(),
        brand_id=brand.id,
        slug="late-prod",
        kind="top_up",
        sort_order=1,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Late Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="LATE-1",
        denomination="1",
        region="GLOBAL",
        price_usd=Decimal("5.00"),
        sort_order=1,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    from yupay.modules.sourcing.models import SkuSourcingRule

    db_session.add(SkuSourcingRule(sku_id=sku.id, mode="force_supplier", supplier_slug="mock"))
    await db_session.commit()
    return str(sku.id)


async def test_a_catalogue_order_paid_after_expiry_is_marked_paid_and_held(
    integration_client: AsyncClient, db_session: AsyncSession, _sku: str
) -> None:
    """Goods do not leave on their own, but the order stops claiming nobody paid.

    ``expired`` on a paid order is a lie, and it hides the order from
    ``list_stuck_paid_orders`` — the one watchdog that exists to notice money
    taken for goods not delivered. Moving it to ``paid`` and holding it puts it
    back under that watchdog, and releasing the hold is the ordinary one-click
    operator action.
    """
    token = await _login(integration_client, tg_id=9713)
    created = await integration_client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "late-order-key-pad"},
        json={"currency": "USD", "items": [{"sku_id": _sku, "qty": 1, "fulfillment_data": {}}]},
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]

    intent = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "late-order-pay-pad"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert intent.status_code in (200, 201), intent.text
    external_id = intent.json()["external_id"]

    await _expire(integration_client, db_session, order_id=order_id, token=token)
    await _settle_mock(integration_client, external_id=external_id, tag="late-order-1")

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    await db_session.refresh(order)
    assert order.status == "paid", "the customer paid; the order must say so"
    assert order.paid_at is not None, "stuck_orders keys on paid_at — without it nobody is told"

    kinds = [
        e.kind
        for e in (
            await db_session.execute(select(OrderEvent).where(OrderEvent.order_id == order_id))
        ).scalars()
    ]
    assert "order.paid_after_expiry" in kinds
    assert "order.held_for_review" in kinds

    tasks = (
        (
            await db_session.execute(
                select(FulfillmentTask).where(FulfillmentTask.order_id == order_id)
            )
        )
        .scalars()
        .all()
    )
    assert tasks == [], "an order we had already written off must not auto-deliver"
