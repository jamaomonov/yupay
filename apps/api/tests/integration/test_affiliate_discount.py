"""Affiliate discount: admission, arithmetic, attribution, and the margin reports.

The reason this module exists at all is the last one. Revenue and margin are
computed from order lines, not from ``total_charged``, so a discount that only
reduced the payable total would be invisible to every report — full margin
shown on precisely the orders that have the least of it.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


def _unique_code(prefix: str) -> str:
    """A collision-free test code.

    Not derived from ``new_id()``: it is a UUIDv7, so its leading characters
    are a timestamp and codes minted inside one test share them.
    """
    return f"{prefix}{secrets.token_hex(5).upper()}"


async def test_order_carries_discount_columns(db_session: AsyncSession) -> None:
    """The new columns exist and default to "no discount"."""
    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.orders.models import Order

    moment = now()
    order = Order(
        id=new_id(),
        guest_email=f"g-{new_id()}@example.test",
        status="pending_payment",
        currency="UZS",
        total_usd=Decimal("1"),
        total_charged=Decimal("12000"),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.refresh(order)

    assert order.affiliate_code_id is None
    assert order.discount_charged == Decimal("0")
