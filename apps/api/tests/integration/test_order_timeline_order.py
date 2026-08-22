"""The order timeline must read in the order things happened.

``order_events.created_at`` defaults to ``CURRENT_TIMESTAMP``, which in
Postgres is the *transaction* start time — so every event written by one
transaction carries the same value to the microsecond. Paying an order writes
``order.paid``, ``order.fulfilling`` and ``order.delivered`` in a single
transaction, so sorting on that column alone is a three-way tie and the
timeline came back in whatever order the planner felt like: the admin page
showed "Доставлен" above "Выдаётся" above "Оплачен".
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

#: What actually happens, in the order it happens.
EXPECTED = ["order.created", "order.paid", "order.fulfilling", "order.delivered"]


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
async def _sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="timeline-cat",
        sort_order=1,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Timeline")],
    )
    brand = Brand(
        id=new_id(),
        category_id=category.id,
        slug="timeline-brand",
        sort_order=1,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Timeline Brand")],
    )
    product = Product(
        id=new_id(),
        brand_id=brand.id,
        slug="timeline-prod",
        kind="top_up",
        sort_order=1,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Timeline Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="TIMELINE-1",
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


async def test_the_admin_timeline_is_in_chronological_order(
    integration_client: AsyncClient, db_session: AsyncSession, _sku: str
) -> None:
    token = await _login(integration_client, tg_id=9801)
    created = await integration_client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "timeline-order-key1"},
        json={"currency": "USD", "items": [{"sku_id": _sku, "qty": 1, "fulfillment_data": {}}]},
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]

    intent = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "timeline-pay-key1xx"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert intent.status_code in (200, 201), intent.text

    hook = await integration_client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {
                "event_id": "evt-timeline-1",
                "payment_id": intent.json()["external_id"],
                "outcome": "succeeded",
            }
        ),
        headers={"content-type": "application/json"},
    )
    assert hook.status_code == 200, hook.text

    admin_token = await _login(integration_client, tg_id=9802)
    await _grant_admin(db_session, tg_id=9802)
    detail = await integration_client.get(
        f"/api/v1/admin/orders/{order_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert detail.status_code == 200, detail.text
    kinds = [e["kind"] for e in detail.json()["events"]]

    # Settlement writes paid/fulfilling/delivered inside one transaction, so
    # all three share a `created_at`; only the id breaks the tie.
    stamps = {e["created_at"] for e in detail.json()["events"]}
    assert len(stamps) < len(kinds), (
        "precondition: this test is meaningless unless some events share a timestamp"
    )
    assert kinds == EXPECTED, f"timeline out of order: {kinds}"
