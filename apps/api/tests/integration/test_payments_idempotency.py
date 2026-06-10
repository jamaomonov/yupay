"""``Idempotency-Key`` on the payment write endpoints (AGENTS.md §9).

``POST /payments/intents`` and ``POST /admin/payments/{id}/refund`` require the
header and replay the persisted result for a repeated key — a client retrying
after a network timeout must get the original outcome, not a 409, even when the
first attempt already walked the order past ``pending_payment``.
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
from sqlalchemy import func, select, update
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
from yupay.modules.payments.models import PaymentAttempt
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
    from yupay.modules.sourcing.models import SkuSourcingRule

    db_session.add(SkuSourcingRule(sku_id=sku.id, mode="force_supplier", supplier_slug="mock"))
    await db_session.commit()
    return sku.id


async def _create_order(client: AsyncClient, *, token: str, sku_id: str, key: str) -> str:
    r = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={
            "currency": "USD",
            "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _create_intent(
    client: AsyncClient, *, token: str, order_id: str, key: str, provider: str = "mock"
):
    return await client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={"order_id": order_id, "provider": provider},
    )


async def _pay_via_webhook(client: AsyncClient, *, external_id: str, event_id: str) -> None:
    wh = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {"event_id": event_id, "payment_id": external_id, "outcome": "succeeded"}
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text


# ---------- intents ----------


async def test_intent_requires_idempotency_key(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=601)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="idem-order-601-pad"
    )
    r = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert r.status_code == 422, r.text


async def test_intent_replay_returns_same_payment(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=602)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="idem-order-602-pad"
    )
    first = await _create_intent(
        integration_client, token=token, order_id=order_id, key="idem-intent-602-pad"
    )
    assert first.status_code == 201, first.text
    again = await _create_intent(
        integration_client, token=token, order_id=order_id, key="idem-intent-602-pad"
    )
    assert again.status_code == 201, again.text
    assert again.json()["id"] == first.json()["id"]


async def test_intent_replay_after_order_paid_returns_original(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    """The timeout-retry case: the first call succeeded and the order moved past
    ``pending_payment``; the retry must replay the original payment, not 409."""
    token = await _login_user(integration_client, tg_id=603)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="idem-order-603-pad"
    )
    first = await _create_intent(
        integration_client, token=token, order_id=order_id, key="idem-intent-603-pad"
    )
    assert first.status_code == 201, first.text
    await _pay_via_webhook(
        integration_client, external_id=first.json()["external_id"], event_id="evt_idem_603"
    )

    again = await _create_intent(
        integration_client, token=token, order_id=order_id, key="idem-intent-603-pad"
    )
    assert again.status_code == 201, again.text
    body = again.json()
    assert body["id"] == first.json()["id"]
    assert body["status"] == "succeeded"


async def test_intent_key_reuse_for_different_order_is_conflict(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=604)
    order_a = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="idem-order-604a-pad"
    )
    order_b = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="idem-order-604b-pad"
    )
    first = await _create_intent(
        integration_client, token=token, order_id=order_a, key="idem-intent-604-pad"
    )
    assert first.status_code == 201, first.text
    reuse = await _create_intent(
        integration_client, token=token, order_id=order_b, key="idem-intent-604-pad"
    )
    assert reuse.status_code == 409, reuse.text


# ---------- refunds ----------


async def test_refund_requires_idempotency_key(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=605)
    await _grant_admin(db_session, tg_id=605)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="idem-order-605-pad"
    )
    intent = await _create_intent(
        integration_client, token=token, order_id=order_id, key="idem-intent-605-pad"
    )
    payment_id = intent.json()["id"]
    r = await integration_client.post(
        f"/api/v1/admin/payments/{payment_id}/refund",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert r.status_code == 422, r.text


async def test_refund_replay_is_noop(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=606)
    await _grant_admin(db_session, tg_id=606)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="idem-order-606-pad"
    )
    intent = await _create_intent(
        integration_client, token=token, order_id=order_id, key="idem-intent-606-pad"
    )
    payment_id = intent.json()["id"]
    await _pay_via_webhook(
        integration_client, external_id=intent.json()["external_id"], event_id="evt_idem_606"
    )

    first = await integration_client.post(
        f"/api/v1/admin/payments/{payment_id}/refund",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "idem-refund-606-pad"},
        json={"reason": "customer request"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "refunded"

    again = await integration_client.post(
        f"/api/v1/admin/payments/{payment_id}/refund",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "idem-refund-606-pad"},
        json={"reason": "customer request"},
    )
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "refunded"

    # Exactly one successful refund attempt — the replay must not re-run the
    # gateway call or book a second ledger posting.
    refund_attempts = (
        await db_session.execute(
            select(func.count())
            .select_from(PaymentAttempt)
            .where(
                PaymentAttempt.payment_id == payment_id,
                PaymentAttempt.kind == "refund",
                PaymentAttempt.status == "ok",
            )
        )
    ).scalar_one()
    assert refund_attempts == 1


async def test_refund_with_new_key_after_full_refund_is_conflict(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=607)
    await _grant_admin(db_session, tg_id=607)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="idem-order-607-pad"
    )
    intent = await _create_intent(
        integration_client, token=token, order_id=order_id, key="idem-intent-607-pad"
    )
    payment_id = intent.json()["id"]
    await _pay_via_webhook(
        integration_client, external_id=intent.json()["external_id"], event_id="evt_idem_607"
    )

    first = await integration_client.post(
        f"/api/v1/admin/payments/{payment_id}/refund",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "idem-refund-607a-pad"},
        json={},
    )
    assert first.status_code == 200, first.text

    second = await integration_client.post(
        f"/api/v1/admin/payments/{payment_id}/refund",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "idem-refund-607b-pad"},
        json={},
    )
    assert second.status_code == 409, second.text
