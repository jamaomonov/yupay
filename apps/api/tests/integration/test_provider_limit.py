"""The per-kassa spend limit (owner, 2026-10-21): Click's mini-app kassa, 90 000 soʻm a day.

Against real Postgres, because the point is the window sum's SQL — which payments count as
the same buyer's — and the settlement paths that hold an order or a top-up on it.
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
from yupay.modules.orders import provider_limit
from yupay.modules.orders.models import Order, OrderEvent, OrderItem
from yupay.modules.orders.risk import REASON_PROVIDER_LIMIT, review_reason
from yupay.modules.payments import service as payments_svc
from yupay.modules.payments.gateways import WebhookEvent
from yupay.modules.payments.models import Payment, PaymentReviewLimit
from yupay.modules.users.models import TelegramLink, User
from yupay.modules.wallet import service as wallet_svc

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
KASSA = "click_miniapp"


async def _sku(db: AsyncSession) -> str:
    """One real SKU, so an order item can carry a player id."""
    category = Category(
        id=new_id(),
        slug=f"pl-cat-{new_id()[-12:]}",
        sort_order=1,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Cat")],
    )
    brand = Brand(
        id=new_id(),
        category_id=category.id,
        slug=f"pl-brand-{new_id()[-12:]}",
        sort_order=1,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Brand")],
    )
    product = Product(
        id=new_id(),
        brand_id=brand.id,
        slug=f"pl-prod-{new_id()[-12:]}",
        kind="top_up",
        sort_order=1,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"PL-{new_id()[-12:]}",
        denomination="1",
        region="GLOBAL",
        price_usd=Decimal("5.00"),
        sort_order=1,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.flush()
    return sku.id


async def _limit(db: AsyncSession, *, max_amount: str = "90000", enabled: bool = True) -> None:
    db.add(
        PaymentReviewLimit(
            provider=KASSA,
            enabled=enabled,
            max_amount=Decimal(max_amount),
            currency="UZS",
            window_hours=24,
        )
    )
    await db.flush()


async def _user(db: AsyncSession, *, trusted: bool = False) -> str:
    user = User(id=new_id())
    if trusted:
        user.trusted_at = now()
    db.add(user)
    await db.flush()
    return user.id


async def _paid(
    db: AsyncSession,
    *,
    user_id: str | None,
    som: str,
    provider: str = KASSA,
    hours_ago: float = 0,
    player_id: str | None = None,
    purpose: str = "catalog",
) -> Order:
    """A paid UZS order with its settled payment, ``hours_ago`` in the past."""
    moment = now() - timedelta(hours=hours_ago)
    order = Order(
        id=new_id(),
        user_id=user_id,
        status="paid",
        currency="UZS",
        total_usd=Decimal("1"),
        total_charged=Decimal(som),
        purpose=purpose,
        expires_at=moment + timedelta(minutes=10),
        paid_at=moment,
    )
    db.add(order)
    await db.flush()
    if player_id is not None:
        db.add(
            OrderItem(
                id=new_id(),
                order_id=order.id,
                sku_id=await _sku(db),
                qty=1,
                unit_price_usd=Decimal("1"),
                fulfillment_data={"player_id": player_id},
            )
        )
    db.add(
        Payment(
            id=new_id(),
            order_id=order.id,
            provider=provider,
            status="succeeded",
            amount=Decimal(som),
            currency="UZS",
            succeeded_at=moment,
        )
    )
    await db.flush()
    return order


async def test_one_payment_over_the_limit_trips_it(db_session: AsyncSession) -> None:
    await _limit(db_session)
    order = await _paid(db_session, user_id=await _user(db_session), som="95000")

    trip = await provider_limit.check(db_session, order)

    assert trip is not None
    assert trip.window_total == Decimal("95000")
    assert trip.max_amount == Decimal("90000")


async def test_paying_in_parts_adds_up(db_session: AsyncSession) -> None:
    """50 000 twice: the first is within the limit, the second carries the sum past it."""
    await _limit(db_session)
    buyer = await _user(db_session)
    first = await _paid(db_session, user_id=buyer, som="50000", hours_ago=2)
    assert await provider_limit.check(db_session, first) is None

    second = await _paid(db_session, user_id=buyer, som="50000")
    trip = await provider_limit.check(db_session, second)

    assert trip is not None
    assert trip.window_total == Decimal("100000")
    assert trip.linked_payments == 1


async def test_a_second_account_paying_for_the_same_player_adds_up(
    db_session: AsyncSession,
) -> None:
    await _limit(db_session)
    await _paid(db_session, user_id=await _user(db_session), som="60000", player_id="584192852")
    other = await _paid(
        db_session, user_id=await _user(db_session), som="40000", player_id=" 584192852 "
    )

    assert await provider_limit.check(db_session, other) is not None


async def test_strangers_old_payments_and_other_kassas_do_not_count(
    db_session: AsyncSession,
) -> None:
    await _limit(db_session)
    buyer = await _user(db_session)
    await _paid(db_session, user_id=await _user(db_session), som="80000")  # someone else
    await _paid(db_session, user_id=buyer, som="80000", hours_ago=25)  # outside the window
    await _paid(db_session, user_id=buyer, som="80000", provider="click")  # the web kassa
    current = await _paid(db_session, user_id=buyer, som="50000")

    assert await provider_limit.check(db_session, current) is None


async def test_a_disabled_limit_or_none_at_all_never_trips(db_session: AsyncSession) -> None:
    order = await _paid(db_session, user_id=await _user(db_session), som="500000")
    assert await provider_limit.check(db_session, order) is None

    await _limit(db_session, enabled=False)
    assert await provider_limit.check(db_session, order) is None


async def test_review_reason_holds_and_a_trusted_account_is_exempt(
    db_session: AsyncSession,
) -> None:
    await _limit(db_session)
    order = await _paid(db_session, user_id=await _user(db_session), som="95000")
    trusted = await _paid(db_session, user_id=await _user(db_session, trusted=True), som="95000")
    await db_session.commit()

    assert await review_reason(db_session, order) == REASON_PROVIDER_LIMIT
    assert await review_reason(db_session, trusted) is None


# ---------- wallet top-ups: held uncredited, credited on release ----------


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    return urlencode({**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()})


async def _admin_headers(client: AsyncClient, db: AsyncSession) -> dict[str, str]:
    user_json = json.dumps({"id": 4243, "first_name": "Admin"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    user_id = (
        await db.execute(select(TelegramLink.user_id).where(TelegramLink.tg_user_id == 4243))
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _settle_topup(db: AsyncSession, *, user_id: str, som: str) -> Order:
    """A pending wallet top-up, settled through the real settlement path."""
    order = Order(
        id=new_id(),
        user_id=user_id,
        status="pending_payment",
        currency="UZS",
        total_usd=Decimal("1"),
        total_charged=Decimal(som),
        purpose="wallet_topup",
        expires_at=now() + timedelta(minutes=10),
    )
    db.add(order)
    await db.flush()
    payment = Payment(
        id=new_id(),
        order_id=order.id,
        provider=KASSA,
        status="pending",
        amount=Decimal(som),
        currency="UZS",
    )
    db.add(payment)
    await db.flush()
    await payments_svc._mark_payment_succeeded(
        db,
        payment=payment,
        event=WebhookEvent(
            external_event_id=f"evt-{order.id}",
            external_payment_id=None,
            outcome="succeeded",
            raw={},
        ),
    )
    await db.commit()
    return order


async def _balance(db: AsyncSession, user_id: str) -> Decimal:
    account = await wallet_svc.ensure_account(
        db, owner_type="user", owner_id=user_id, kind="user_wallet", currency="UZS"
    )
    return await wallet_svc.balance(db, account.id)


async def test_topping_up_in_parts_is_held_uncredited_then_released(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _limit(db_session)
    buyer = await _user(db_session)
    await _settle_topup(db_session, user_id=buyer, som="50000")
    held = await _settle_topup(db_session, user_id=buyer, som="50000")

    await db_session.refresh(held)
    assert held.status == "paid", "held, not delivered"
    assert await _balance(db_session, buyer) == Decimal("50000"), "only the first one credited"
    events = (
        await db_session.execute(select(OrderEvent.payload).where(OrderEvent.order_id == held.id))
    ).scalars()
    assert any(p.get("reason") == REASON_PROVIDER_LIMIT for p in events)

    headers = await _admin_headers(integration_client, db_session)
    url = f"/api/v1/admin/fulfillment/orders/{held.id}/release"
    first = await integration_client.post(url, headers=headers)
    again = await integration_client.post(url, headers=headers)

    assert first.status_code == 200, first.text
    assert again.status_code == 200, "a second click is a no-op"
    await db_session.refresh(held)
    assert held.status == "delivered"
    assert await _balance(db_session, buyer) == Decimal("100000")


async def test_refunding_a_held_topup_leaves_the_balance_alone(
    db_session: AsyncSession,
) -> None:
    """The money never reached the balance, so the refund must not take it back off it."""
    await _limit(db_session)
    buyer = await _user(db_session)
    await _settle_topup(db_session, user_id=buyer, som="60000")
    held = await _settle_topup(db_session, user_id=buyer, som="60000")
    payment = (
        await db_session.execute(select(Payment).where(Payment.order_id == held.id))
    ).scalar_one()
    assert not await wallet_svc.topup_was_credited(db_session, payment_id=payment.id)

    await payments_svc._book_refund_ledger(
        db_session,
        payment=payment,
        order=held,
        refund_amount=payment.amount,
        reason="cabinet refund",
        is_full=True,
        actor="test",
    )
    await db_session.commit()

    assert await _balance(db_session, buyer) == Decimal("60000")


# ---------- admin ----------


async def test_the_admin_lists_and_sets_a_kassa_limit(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session)

    put = await integration_client.put(
        f"/api/v1/admin/payments/review-limits/{KASSA}",
        json={"enabled": True, "max_amount": "75000", "window_hours": 12},
        headers={**headers, "Idempotency-Key": "limit-set-0001-abcdef"},
    )
    listed = await integration_client.get("/api/v1/admin/payments/review-limits", headers=headers)
    unknown = await integration_client.put(
        "/api/v1/admin/payments/review-limits/nope",
        json={"enabled": True, "max_amount": "1"},
        headers=headers,
    )
    anonymous = await integration_client.get("/api/v1/admin/payments/review-limits")

    assert put.status_code == 200, put.text
    assert Decimal(put.json()["max_amount"]) == Decimal("75000")
    assert listed.status_code == 200, listed.text
    row = next(i for i in listed.json()["items"] if i["provider"] == KASSA)
    assert row["enabled"] is True
    assert row["window_hours"] == 12
    assert unknown.status_code == 404
    assert anonymous.status_code in (401, 403)
