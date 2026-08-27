"""Binding a buyer to the partner who introduced them.

Written in the transaction that marks a catalog order paid, not when the order
was created: an abandoned cart must not tie a buyer forever to a partner who
sold them nothing.

``UNIQUE(user_id)`` on ``affiliate_attributions`` is what makes the write
race-safe without a lock. Two payments landing at once both try to insert; one
wins, the other reports ``False``.

Nothing here raises. A payment webhook is an acquirer telling us money moved,
and the affiliate program must never be the reason we fail to record that.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.affiliate.models import AffiliateAttribution, AffiliateCode
from yupay.modules.orders.models import Order

log = get_logger("yupay.affiliate.attribution")


async def bind_attribution(db: AsyncSession, *, order: Order) -> bool:
    """Bind this order's buyer to its code's partner, if it is their first.

    Args:
        db: Session. The caller owns the transaction.
        order: The order that has just been marked paid.

    Returns:
        ``True`` if an attribution was created. ``False`` — never an exception —
        when there is nothing to bind (a guest, no code, a top-up) or when a
        concurrent payment won the race.
    """
    if order.user_id is None or order.affiliate_code_id is None:
        return False
    if order.purpose != "catalog":
        return False

    code = (
        await db.execute(select(AffiliateCode).where(AffiliateCode.id == order.affiliate_code_id))
    ).scalar_one_or_none()
    if code is None:
        return False

    try:
        # The row is added *inside* the SAVEPOINT, not before it. Added
        # outside, a failed flush leaves the doomed object in ``session.new``
        # and SQLAlchemy poisons the whole session with PendingRollbackError —
        # so losing this race would roll back the payment settlement that owns
        # the outer transaction. Inside, the savepoint rollback discards it.
        async with db.begin_nested():
            db.add(
                AffiliateAttribution(
                    id=new_id(),
                    user_id=order.user_id,
                    partner_id=code.partner_id,
                    code_id=code.id,
                    first_order_id=order.id,
                )
            )
            await db.flush()
    except IntegrityError:
        return False

    log.info("affiliate.attribution.bound", order_id=order.id)
    return True


__all__ = ["bind_attribution"]
