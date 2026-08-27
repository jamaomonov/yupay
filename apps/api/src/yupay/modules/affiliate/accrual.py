"""The commission sweep: find work, post it, record it.

Deliberately not called from the fulfilment path. That path is already the
slowest in the system and is where a customer waits for a code; adding money
work to it buys a minute of freshness in a panel that sits behind a two-week
hold period anyway.

The design's safety property is that this function can be run at any time, any
number of times, concurrently with itself, and never pay twice —
``UNIQUE(order_id)`` on ``affiliate_commissions`` decides the winner, and the
ledger posting is keyed off the commission row's own id. An order missed for
any reason is picked up by the next pass, so there is nothing to reconcile by
hand.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.affiliate.ledger import (
    commission_amount,
    post_accrual,
    post_maturation,
    post_void,
)
from yupay.modules.affiliate.models import (
    AffiliateAttribution,
    AffiliateCode,
    AffiliateCommission,
)
from yupay.modules.orders.models import Order

log = get_logger("yupay.affiliate.accrual")


async def accrue_commissions(db: AsyncSession, *, hold_days: int, limit: int = 500) -> int:
    """Accrue commission for delivered, attributed orders that have none yet.

    Args:
        db: Session. The caller owns the transaction.
        hold_days: Days from now until the commission becomes withdrawable.
        limit: Maximum orders handled in one pass, so a backlog drains over
            several passes rather than in one long transaction.

    Returns:
        How many commissions were accrued.
    """
    rows = (
        await db.execute(
            select(Order, AffiliateAttribution, AffiliateCode)
            .join(AffiliateAttribution, AffiliateAttribution.user_id == Order.user_id)
            .join(AffiliateCode, AffiliateCode.id == AffiliateAttribution.code_id)
            .outerjoin(AffiliateCommission, AffiliateCommission.order_id == Order.id)
            .where(
                Order.status == "delivered",
                Order.delivered_at.isnot(None),
                # Wallet top-ups are 1:1 deposits, not sales. Paying commission
                # on one would pay a partner for the buyer moving their own
                # money, and would pay again on the order it then funds.
                Order.purpose == "catalog",
                AffiliateCommission.id.is_(None),
            )
            .order_by(Order.delivered_at)
            .limit(limit)
        )
    ).all()

    accrued = 0
    for order, attribution, code in rows:
        amount = commission_amount(order.total_charged, code.commission_percent, order.currency)
        if amount <= 0:
            continue
        commission = AffiliateCommission(
            id=new_id(),
            order_id=order.id,
            partner_id=attribution.partner_id,
            code_id=code.id,
            base_amount=order.total_charged,
            percent=code.commission_percent,
            amount=amount,
            currency=order.currency,
            status="pending",
            available_at=now() + timedelta(days=hold_days),
        )
        db.add(commission)
        try:
            # Settle the UNIQUE before posting: if a concurrent pass already
            # took this order, we must not put money in the ledger for it.
            # SAVEPOINT rather than a bare flush, because the outer transaction
            # belongs to the caller and losing this race must not end it.
            async with db.begin_nested():
                await db.flush()
        except IntegrityError:
            continue
        await post_accrual(
            db,
            commission_id=commission.id,
            partner_id=commission.partner_id,
            amount=amount,
            currency=order.currency,
            order_id=order.id,
        )
        accrued += 1

    if accrued:
        log.info("affiliate.accrual.accrued", count=accrued)
    return accrued


async def mature_commissions(db: AsyncSession, *, limit: int = 500) -> int:
    """Release commissions whose hold period has expired.

    Args:
        db: Session. The caller owns the transaction.
        limit: Maximum rows handled in one pass.

    Returns:
        How many commissions became available.
    """
    moment = now()
    rows = (
        await db.execute(
            select(AffiliateCommission)
            .where(
                AffiliateCommission.status == "pending",
                AffiliateCommission.available_at <= moment,
            )
            .order_by(AffiliateCommission.available_at)
            .limit(limit)
            # Two overlapping passes must not both mature the same row. The
            # deterministic idempotency key on the posting is the second line
            # of defence; this is the first, and it lets the other pass get on
            # with the rows it can have rather than blocking on ours.
            .with_for_update(skip_locked=True)
        )
    ).scalars()

    matured = 0
    for commission in rows:
        await post_maturation(
            db,
            commission_id=commission.id,
            partner_id=commission.partner_id,
            amount=commission.amount,
            currency=commission.currency,
        )
        commission.status = "available"
        matured += 1

    if matured:
        log.info("affiliate.accrual.matured", count=matured)
    return matured


async def void_commission(db: AsyncSession, *, order_id: str) -> bool:
    """Reverse the commission on a refunded order, if it is still held.

    Args:
        db: Session. The caller owns the transaction.
        order_id: The order that was refunded or cancelled.

    Returns:
        ``True`` if a commission was reversed; ``False`` if there was none, or
        it had already matured, or it was already void. A matured commission is
        deliberately left alone — it may already sit inside a payout request,
        and clawing back money a partner can see is an admin's decision, not a
        sweep's. See the spec's "Refunds" note.
    """
    commission = (
        await db.execute(
            select(AffiliateCommission)
            .where(AffiliateCommission.order_id == order_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if commission is None or commission.status != "pending":
        return False

    await post_void(
        db,
        commission_id=commission.id,
        partner_id=commission.partner_id,
        amount=commission.amount,
        currency=commission.currency,
    )
    commission.status = "void"
    log.info("affiliate.accrual.voided", order_id=order_id)
    return True


__all__ = ["accrue_commissions", "mature_commissions", "void_commission"]
