"""A refund made in Click's cabinet, booked from the order page.

Click sends no callback for a refund, so the operator records it:
``POST /admin/payments/{id}/record-cabinet-refund``. The order and payment walk
to ``refunded`` once, and only a Click payment can be booked this way.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.orders.models import Order, OrderEvent
from yupay.modules.payments.models import Payment
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _paid(db: AsyncSession, *, provider: str) -> tuple[str, str]:
    user_id, order_id, payment_id = (str(uuid.uuid4()) for _ in range(3))
    db.add(User(id=user_id, roles=[]))
    await db.flush()
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            status="delivered",
            currency="UZS",
            total_usd=Decimal("10.00"),
            total_charged=Decimal("130000.00"),
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    await db.flush()
    db.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider=provider,
            status="succeeded",
            amount=Decimal("130000.00"),
            currency="UZS",
        )
    )
    await db.commit()
    return order_id, payment_id


def _body(reference: str = "click-refund-77") -> dict[str, str]:
    return {"reason": "код не активируется", "provider_reference": reference}


async def test_a_click_refund_is_booked_once(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    order_id, payment_id = await _paid(db_session, provider="click")
    url = f"/api/v1/admin/payments/{payment_id}/record-cabinet-refund"

    first = await integration_client.post(
        url, json=_body(), headers={**admin_headers, "Idempotency-Key": f"cab-{payment_id}-1"}
    )
    again = await integration_client.post(
        url, json=_body(), headers={**admin_headers, "Idempotency-Key": f"cab-{payment_id}-2"}
    )

    assert first.status_code == 200, first.text
    refund = first.json()["extra_metadata"]["last_refund"]
    assert (refund["refunded_to"], refund["provider_reference"]) == ("card", "click-refund-77")
    assert again.status_code == 409, "a refunded payment is never booked twice"
    order = await db_session.get(Order, order_id)
    payment = await db_session.get(Payment, payment_id)
    assert order is not None
    assert payment is not None
    await db_session.refresh(order)
    await db_session.refresh(payment)
    assert (order.status, payment.status) == ("refunded", "refunded")
    kinds = {
        e.kind
        for e in (
            await db_session.execute(
                OrderEvent.__table__.select().where(OrderEvent.order_id == order_id)
            )
        ).all()
    }
    assert "admin.cabinet_refund_recorded" in kinds


async def test_only_a_click_payment_is_booked_by_hand(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    _, payment_id = await _paid(db_session, provider="payme")

    response = await integration_client.post(
        f"/api/v1/admin/payments/{payment_id}/record-cabinet-refund",
        json=_body(),
        headers={**admin_headers, "Idempotency-Key": f"cab-{payment_id}"},
    )

    assert response.status_code == 409
    assert response.json()["reason"] == "provider"
