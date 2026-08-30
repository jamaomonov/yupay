"""Large paid orders are held instead of fulfilled (ADR-0047).

The assertion that matters is negative — that fulfilment did NOT run — which
only a real payment through the real webhook can establish. A unit test of the
rule proves the threshold; only this proves the rule is wired into the one path
money actually takes.
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
from yupay.modules.orders.models import Order, OrderEvent
from yupay.modules.users.models import TelegramLink, User

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
    return r.json()["access_token"]


@pytest.fixture
async def _sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="hold-cat",
        sort_order=1,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Hold")],
    )
    brand = Brand(
        id=new_id(),
        category_id=category.id,
        slug="hold-brand",
        sort_order=1,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Hold Brand")],
    )
    product = Product(
        id=new_id(),
        brand_id=brand.id,
        slug="hold-prod",
        kind="top_up",
        sort_order=1,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Hold Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="HOLD-1",
        denomination="1",
        region="GLOBAL",
        price_usd=Decimal("100.00"),
        sort_order=1,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    from yupay.modules.sourcing.models import SkuSourcingRule

    db_session.add(SkuSourcingRule(sku_id=sku.id, mode="force_supplier", supplier_slug="mock"))
    await db_session.commit()
    return sku.id


async def _buy(client: AsyncClient, *, token: str, sku_id: str, tag: str) -> str:
    r = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"idem-{tag}-padding"},
        json={"currency": "USD", "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}]},
    )
    assert r.status_code == 201, r.text
    order_id = r.json()["id"]

    intent = await client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"idem-pay-{tag}-pad"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert intent.status_code in (200, 201), intent.text
    external_id = intent.json()["external_id"]

    hook = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {"event_id": f"evt-{tag}", "payment_id": external_id, "outcome": "succeeded"}
        ),
        headers={"content-type": "application/json"},
    )
    assert hook.status_code == 200, hook.text
    return order_id


@pytest.fixture
def _threshold_40(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MANUAL_REVIEW_THRESHOLD_USD", "40")
    cfg.get_settings.cache_clear()
    yield
    monkeypatch.delenv("MANUAL_REVIEW_THRESHOLD_USD", raising=False)
    cfg.get_settings.cache_clear()


async def test_a_large_order_is_paid_but_not_fulfilled(
    integration_client: AsyncClient, db_session: AsyncSession, _sku: str, _threshold_40: None
) -> None:
    """The whole point: the money lands, the goods do not leave."""
    order_id = await _buy(
        integration_client,
        token=await _login(integration_client, 8801),
        sku_id=_sku,
        tag="hold-8801",
    )

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status == "paid", "payment must still settle — a hold is not a rejection"
    assert order.paid_at is not None
    assert order.delivered_at is None

    tasks = (
        (
            await db_session.execute(
                select(FulfillmentTask).where(FulfillmentTask.order_id == order_id)
            )
        )
        .scalars()
        .all()
    )
    assert tasks == [], "fulfilment must not have started"

    kinds = [
        e.kind
        for e in (
            await db_session.execute(select(OrderEvent).where(OrderEvent.order_id == order_id))
        ).scalars()
    ]
    assert "order.held_for_review" in kinds
    # The customer-visible state is unchanged, so nothing new had to be taught
    # to the storefront or the mini app.
    assert "order.fulfilling" not in kinds


async def test_releasing_the_hold_fulfils_the_order(
    integration_client: AsyncClient, db_session: AsyncSession, _sku: str, _threshold_40: None
) -> None:
    """Release is the same call the webhook skipped — not an undo."""
    token = await _login(integration_client, 8802)
    order_id = await _buy(integration_client, token=token, sku_id=_sku, tag="hold-8802")

    admin_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == 8802)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == admin_id).values(roles=["admin"]))
    await db_session.commit()
    admin_token = await _login(integration_client, 8802)

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/orders/{order_id}/release",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 1

    await db_session.commit()
    tasks = (
        (
            await db_session.execute(
                select(FulfillmentTask).where(FulfillmentTask.order_id == order_id)
            )
        )
        .scalars()
        .all()
    )
    assert tasks, "release must create the fulfilment work the hold withheld"


async def test_an_ordinary_order_is_untouched(
    integration_client: AsyncClient, db_session: AsyncSession, _sku: str, _threshold_40: None
) -> None:
    """A control that also stops ordinary sales is not a control, it is an outage.

    The SKU is $100, so the amount threshold is raised above it for this one
    case rather than seeding a second product. The identity-window rules
    (ADR-0062) are also disabled here: a lone $100 order is, by itself,
    already at or above their default sums (``RISK_SUM_24H_USD``/
    ``RISK_SUM_7D_USD`` = 25/60) with no siblings needed, so this control
    would otherwise be held by a rule it isn't testing. What's under test is
    specifically "below the amount threshold fulfils automatically" — the
    window rules get their own coverage in ``test_order_risk_windows.py``.
    """
    import os

    os.environ["MANUAL_REVIEW_THRESHOLD_USD"] = "500"
    os.environ["RISK_SUM_24H_USD"] = "0"
    os.environ["RISK_SUM_7D_USD"] = "0"
    os.environ["RISK_VELOCITY_24H"] = "0"
    os.environ["RISK_DISTINCT_BUYERS_7D"] = "0"
    cfg.get_settings.cache_clear()
    try:
        order_id = await _buy(
            integration_client,
            token=await _login(integration_client, 8803),
            sku_id=_sku,
            tag="hold-8803",
        )
        tasks = (
            (
                await db_session.execute(
                    select(FulfillmentTask).where(FulfillmentTask.order_id == order_id)
                )
            )
            .scalars()
            .all()
        )
        assert tasks, "an order below the threshold must fulfil automatically"
    finally:
        os.environ["MANUAL_REVIEW_THRESHOLD_USD"] = "40"
        os.environ["RISK_SUM_24H_USD"] = "25"
        os.environ["RISK_SUM_7D_USD"] = "60"
        os.environ["RISK_VELOCITY_24H"] = "5"
        os.environ["RISK_DISTINCT_BUYERS_7D"] = "3"
        cfg.get_settings.cache_clear()
