"""Admin «Возврат на баланс»: a payment refunded in full onto the customer's balance."""

from __future__ import annotations

from decimal import Decimal
from types import ModuleType

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import ConflictError
from yupay.core.ids import new_id
from yupay.modules.orders.models import Order
from yupay.modules.payments.models import Payment
from yupay.modules.wallet import service as wallet

from tests.integration.test_fulfillment_async import _make_paid_order
from tests.integration.test_guest_delivery_access import _admin_headers

pytestmark = pytest.mark.asyncio

AMOUNT = Decimal("31257")


def _payments() -> ModuleType:
    # Lazy: payments.service <-> wallet.api <-> api.v1 is a known import cycle.
    from yupay.modules.payments import service

    return service


async def _paid(db: AsyncSession, tag: str) -> tuple[Order, Payment]:
    order = await _make_paid_order(db, tag=tag)
    payment = Payment(
        id=new_id(),
        order_id=order.id,
        provider="uzum",
        status="succeeded",
        amount=AMOUNT,
        currency="UZS",
        extra_metadata={},
    )
    db.add(payment)
    await db.commit()
    return order, payment


async def _balance(db: AsyncSession, user_id: str) -> Decimal:
    acc = await wallet.ensure_account(
        db, owner_type="user", owner_id=user_id, kind="user_wallet", currency="UZS"
    )
    return await wallet.balance(db, acc.id)


async def test_refund_lands_on_the_balance_once(db_session: AsyncSession) -> None:
    order, payment = await _paid(db_session, "arw-once")
    user_id = order.user_id
    assert user_id is not None
    svc = _payments()

    await svc.refund_admin_to_wallet(
        db_session,
        payment_id=payment.id,
        admin_id=new_id(),
        reason="sold out",
        idempotency_key="k1",
    )
    await db_session.commit()
    # The same key is a replay; a new key is a second refund and is refused.
    await svc.refund_admin_to_wallet(
        db_session, payment_id=payment.id, admin_id=new_id(), idempotency_key="k1"
    )
    with pytest.raises(ConflictError):
        await svc.refund_admin_to_wallet(
            db_session, payment_id=payment.id, admin_id=new_id(), idempotency_key="k2"
        )
    await db_session.rollback()

    assert await _balance(db_session, user_id) == AMOUNT
    await db_session.refresh(payment)
    await db_session.refresh(order)
    assert payment.status == "refunded"
    assert svc.refunded_to_wallet(payment)
    assert order.status == "refunded"
    # And the card refund cannot follow it.
    with pytest.raises(ConflictError):
        await svc.refund_admin(db_session, payment_id=payment.id, admin_id=new_id())


async def test_a_guest_order_is_refused(db_session: AsyncSession) -> None:
    order, payment = await _paid(db_session, "arw-guest")
    await db_session.execute(
        update(Order)
        .where(Order.id == order.id)
        .values(user_id=None, guest_email="guest@example.com")
    )
    await db_session.commit()
    with pytest.raises(ConflictError):
        await _payments().refund_admin_to_wallet(
            db_session, payment_id=payment.id, admin_id=new_id()
        )


async def test_a_balance_top_up_is_refused(db_session: AsyncSession) -> None:
    order, payment = await _paid(db_session, "arw-topup")
    await db_session.execute(
        update(Order).where(Order.id == order.id).values(purpose="wallet_topup")
    )
    await db_session.commit()
    with pytest.raises(ConflictError):
        await _payments().refund_admin_to_wallet(
            db_session, payment_id=payment.id, admin_id=new_id()
        )


async def test_route_requires_a_key_and_refunds(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order, payment = await _paid(db_session, "arw-route")
    assert order.user_id is not None
    headers = await _admin_headers(integration_client, db_session, **tag_id(order.id))
    url = f"/api/v1/admin/payments/{payment.id}/refund-to-wallet"

    no_key = await integration_client.post(url, headers=headers, json={"reason": "x"})
    assert no_key.status_code == 422, no_key.text

    ok = await integration_client.post(
        url, headers={**headers, "Idempotency-Key": f"arw-{new_id()}"}, json={"reason": "x"}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "refunded"
    assert await _balance(db_session, order.user_id) == AMOUNT


def tag_id(seed: str) -> dict[str, int]:
    """A Telegram id per test, so admin logins never collide."""
    return {"tg_id": 7_400_000 + int(seed.replace("-", "")[-5:], 16) % 90_000}


async def test_an_unknown_payment_is_404(db_session: AsyncSession) -> None:
    from yupay.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await _payments().refund_admin_to_wallet(db_session, payment_id=new_id(), admin_id=new_id())
