"""The dashboard's three numbers: orders, delivered, spend — since a moment.

**Since a moment the caller names**, not "today". The cabinet renders every
timestamp in the viewer's browser zone, so it is the browser that knows when
its own day started; a server that decided "today" from a stored preference
would print a count that disagreed with the dates on the Orders list two
screens over. The merchant's `timezone` field decides when we mail them and
nothing else — see ADR-0076 and the runbook.

The counts are exact. The money is read from the **ledger**, like every other
money on this surface, over a bounded window — see :data:`MAX_ORDERS`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.errors import ValidationError
from yupay.modules.merchants import deposit
from yupay.modules.merchants.cabinet_schemas import CabinetSummaryOut
from yupay.modules.orders.models import Order

#: How many orders' worth of ledger the spend figure will read. A dashboard
#: number is a glance, not a report: past this the figure is reported as a
#: floor (``spend_capped``) and the Orders list is the authority. Chosen so
#: that a busy day for the resellers we have costs one bounded batch read.
MAX_ORDERS: Final = 500

#: How far back a caller may ask. The window is a *day* on every real call;
#: the bound exists so a crafted `since` cannot turn a dashboard read into a
#: scan of the whole order history.
MAX_WINDOW: Final = timedelta(days=32)


async def build(
    db: AsyncSession, *, merchant_id: str, since: datetime, now: datetime
) -> CabinetSummaryOut:
    """Summarise one merchant's orders placed at or after ``since``.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Taken from the signed-in operator, never from a request
            field.
        since: Start of the window, inclusive. The browser sends its own local
            midnight, expressed in UTC.
        now: Current time, for bounding the window.

    Returns:
        Counts and net spend. ``delivered`` and ``failed`` are the two
        terminal outcomes, so a success rate is theirs to compute and never
        includes orders still in flight. ``spend_capped`` says the window held
        more than :data:`MAX_ORDERS` orders and the figure is therefore a
        floor.

    Raises:
        ValidationError: ``since`` is in the future or older than
            :data:`MAX_WINDOW`.
    """
    if since > now:
        raise ValidationError("since is in the future", code="bad_window")
    if now - since > MAX_WINDOW:
        raise ValidationError(
            "window is longer than this summary will read", code="window_too_long"
        )

    scoped = (Order.merchant_id == merchant_id, Order.created_at >= since)
    orders = (await db.execute(select(func.count()).select_from(Order).where(*scoped))).scalar_one()
    delivered = (
        await db.execute(
            select(func.count()).select_from(Order).where(*scoped, Order.status == "delivered")
        )
    ).scalar_one()
    # ``failed`` only — not ``cancelled``, which is a decision somebody made,
    # and not ``refunded``, which is about money rather than about delivery.
    failed = (
        await db.execute(
            select(func.count()).select_from(Order).where(*scoped, Order.status == "failed")
        )
    ).scalar_one()

    ids = list(
        (
            await db.execute(
                select(Order.id)
                .where(*scoped)
                .order_by(Order.created_at.desc())
                .limit(MAX_ORDERS + 1)
            )
        )
        .scalars()
        .all()
    )
    capped = len(ids) > MAX_ORDERS
    pairs = [(merchant_id, order_id) for order_id in ids[:MAX_ORDERS]]
    charged = await deposit.charged_for_orders(db, pairs=pairs)
    refunded = await deposit.refunded_for_orders(db, pairs=pairs)
    # Net: what the deposit is out by for *these* orders, counting refunds
    # against them whenever those were posted. A gross figure would have a
    # reseller chasing money that already came back.
    spend = sum(charged.values(), Decimal("0")) - sum(refunded.values(), Decimal("0"))

    return CabinetSummaryOut(
        orders=orders,
        delivered=delivered,
        failed=failed,
        spend_usd=spend,
        spend_capped=capped,
    )


__all__ = ["MAX_ORDERS", "MAX_WINDOW", "build"]
