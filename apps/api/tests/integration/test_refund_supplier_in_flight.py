"""A full refund must wait while a supplier is still working on the order.

A refund cancels the order's open fulfilment tasks. No supplier adapter can
recall a purchase (every ``cancel()`` raises ``FulfillerNotIntegratedError``),
so cancelling an ``in_progress`` task only cancelled it on our side: the
supplier delivered minutes later and the buyer had the goods and the money.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import ConflictError
from yupay.core.ids import new_id
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import OrderItem
from yupay.modules.payments.models import Payment
from yupay.modules.payments.service import refund_admin

from tests.integration.test_fulfillment_async import _make_paid_order

pytestmark = pytest.mark.asyncio


async def _order_with_task(
    db: AsyncSession, tag: str, *, supplier: str, status: str
) -> tuple[str, str]:
    """Return ``(order_id, payment_id)``."""
    order = await _make_paid_order(db, tag=tag)
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
    existing = (
        await db.execute(select(FulfillmentTask).where(FulfillmentTask.order_item_id == item.id))
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            FulfillmentTask(
                id=new_id(),
                order_id=order.id,
                order_item_id=item.id,
                supplier=supplier,
                status=status,
                extra_metadata={},
            )
        )
    else:
        existing.supplier = supplier
        existing.status = status
    payment_id = new_id()
    db.add(
        Payment(
            id=payment_id,
            order_id=order.id,
            provider="wallet",
            status="succeeded",
            amount=Decimal("130000"),
            currency="UZS",
            extra_metadata={},
        )
    )
    await db.commit()
    return order.id, payment_id


async def test_refund_is_refused_while_a_supplier_purchase_is_in_flight(
    db_session: AsyncSession,
) -> None:
    _, payment_id = await _order_with_task(
        db_session, "rsf-nova", supplier="nova", status="in_progress"
    )
    with pytest.raises(ConflictError) as err:
        await refund_admin(db_session, payment_id=payment_id, admin_id=new_id())
    assert err.value.extra["reason"] == "supplier_purchase_in_flight"


@pytest.mark.parametrize(
    ("supplier", "status"),
    [
        ("nova", "pending"),  # not sent yet: cancelling it really stops it
        ("nova", "failed"),
        ("manual", "in_progress"),  # a human queue we stop ourselves
        ("inventory", "in_progress"),
    ],
)
async def test_refund_goes_ahead_when_nothing_is_out_with_a_supplier(
    db_session: AsyncSession, supplier: str, status: str
) -> None:
    from yupay.modules.fulfillment.service import supplier_purchase_in_flight

    order_id, _ = await _order_with_task(
        db_session, f"rsf-{supplier}-{status}", supplier=supplier, status=status
    )
    assert await supplier_purchase_in_flight(db_session, order_id) is False
