"""Admin «Вернуть позицию на баланс»: one failed line of a cart paid back, the order closes."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import ConflictError
from yupay.core.ids import new_id
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.payments.models import Payment

from tests.integration.test_admin_refund_to_wallet import _balance, _payments, tag_id
from tests.integration.test_fulfillment_async import _make_paid_order
from tests.integration.test_guest_delivery_access import _admin_headers

pytestmark = pytest.mark.asyncio

AMOUNT = Decimal("36000")


async def _cart(
    db: AsyncSession, tag: str, statuses: list[str]
) -> tuple[Order, Payment, list[str]]:
    """A three-line cart paid by card, its tasks in ``statuses``, line order kept."""
    order = await _make_paid_order(db, tag=tag, n_items=len(statuses))
    await db.execute(update(Order).where(Order.id == order.id).values(status="fulfilling"))
    items = (
        (
            await db.execute(
                select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)
            )
        )
        .scalars()
        .all()
    )
    for item, status in zip(items, statuses, strict=True):
        db.add(
            FulfillmentTask(
                id=new_id(),
                order_id=order.id,
                order_item_id=item.id,
                supplier="mock",
                status=status,
                extra_metadata={},
            )
        )
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
    return order, payment, [i.id for i in items]


async def test_a_failed_line_goes_back_once_and_the_order_closes(db_session: AsyncSession) -> None:
    from yupay.modules.payments import line_refund

    order, payment, items = await _cart(
        db_session, "lrw-once", ["succeeded", "succeeded", "failed"]
    )
    assert order.user_id is not None

    await line_refund.refund_line_to_wallet(
        db_session, order_item_id=items[2], admin_id=new_id(), idempotency_key="k1"
    )
    await db_session.commit()
    # A replay is a no-op, not a second credit.
    await line_refund.refund_line_to_wallet(
        db_session, order_item_id=items[2], admin_id=new_id(), idempotency_key="k2"
    )
    await db_session.commit()

    assert await _balance(db_session, order.user_id) == Decimal("12000")
    await db_session.refresh(payment)
    await db_session.refresh(order)
    assert payment.status == "partially_refunded"
    assert order.status == "delivered"
    line = (
        await db_session.execute(select(OrderItem).where(OrderItem.id == items[2]))
    ).scalar_one()
    await db_session.refresh(line)
    assert line.fulfillment_state == "refunded"
    svc = _payments()
    # Neither whole-payment refund nor an acquirer cancel can follow it.
    assert svc.refunded_to_wallet(payment)
    with pytest.raises(ConflictError):
        await svc.refund_admin_to_wallet(db_session, payment_id=payment.id, admin_id=new_id())


async def test_a_delivered_or_running_line_is_refused(db_session: AsyncSession) -> None:
    from yupay.modules.payments import line_refund

    _, _, items = await _cart(db_session, "lrw-busy", ["succeeded", "in_progress"])
    for item_id in items:
        with pytest.raises(ConflictError):
            await line_refund.refund_line_to_wallet(
                db_session, order_item_id=item_id, admin_id=new_id(), idempotency_key="k"
            )
        await db_session.rollback()


async def test_nothing_delivered_means_refund_the_whole_payment(db_session: AsyncSession) -> None:
    from yupay.modules.payments import line_refund

    _, _, items = await _cart(db_session, "lrw-none", ["failed", "failed"])
    with pytest.raises(ConflictError):
        await line_refund.refund_line_to_wallet(
            db_session, order_item_id=items[0], admin_id=new_id(), idempotency_key="k"
        )


async def test_two_failed_lines_each_go_back(db_session: AsyncSession) -> None:
    from yupay.modules.payments import line_refund

    order, _, items = await _cart(db_session, "lrw-two", ["succeeded", "failed", "cancelled"])
    assert order.user_id is not None
    await line_refund.refund_line_to_wallet(
        db_session, order_item_id=items[1], admin_id=new_id(), idempotency_key="k1"
    )
    await db_session.commit()
    await db_session.refresh(order)
    assert order.status == "fulfilling"  # one line still unresolved
    await line_refund.refund_line_to_wallet(
        db_session, order_item_id=items[2], admin_id=new_id(), idempotency_key="k2"
    )
    await db_session.commit()
    await db_session.refresh(order)
    assert order.status == "delivered"
    assert await _balance(db_session, order.user_id) == Decimal("24000")


async def test_route_requires_a_key(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order, _, items = await _cart(db_session, "lrw-route", ["succeeded", "failed"])
    headers = await _admin_headers(integration_client, db_session, **tag_id(order.id))
    url = f"/api/v1/admin/payments/order-items/{items[1]}/refund-to-wallet"

    no_key = await integration_client.post(url, headers=headers)
    assert no_key.status_code == 422, no_key.text
    ok = await integration_client.post(
        url, headers={**headers, "Idempotency-Key": f"lrw-{new_id()}"}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "partially_refunded"
