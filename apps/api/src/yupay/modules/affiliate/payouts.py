"""Withdrawing earned commission.

Two mechanisms together make a payout request safe to race, and it is worth
being precise about which does what, because either alone is not enough.

The **row lock** on the partner serialises concurrent requests: without it two
transactions both read the full balance before either writes, and both pass
their check. `SELECT ... FOR UPDATE` makes the second wait for the first.

The **ledger reservation** is what the second one then sees. `post_payout_hold`
moves the money out of ``partner_balance`` into ``partner_payout_hold``, so the
second request's balance check reads the reduced figure rather than the
original. Reserving without locking would still race; locking without reserving
would let a partner queue two requests against one balance.

Card details are stored because the transfer is made by hand. They are PII of
the worst kind in this codebase and must never reach a log line — nothing here
logs the request body, and the tests assert it.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.affiliate.ledger import (
    post_payout_hold,
    post_payout_paid,
    post_payout_rejected,
)
from yupay.modules.affiliate.models import AffiliatePartner, AffiliatePayout
from yupay.modules.affiliate.panel import DEFAULT_CURRENCY, account_balance

log = get_logger("yupay.affiliate.payouts")


async def request_payout(
    db: AsyncSession,
    *,
    partner_id: str,
    amount: Decimal,
    card_number: str,
    card_holder: str,
    currency: str = DEFAULT_CURRENCY,
    settings: Settings | None = None,
) -> AffiliatePayout:
    """Reserve money for a withdrawal and record the request.

    Args:
        db: Session. The caller owns the transaction.
        partner_id: From the caller's token, never from the request body.
        amount: How much to withdraw, in ``currency``.
        card_number: Where to send it. PII — never logged.
        card_holder: The name on the card. PII — never logged.
        currency: The partner's currency.
        settings: Overrides the process settings; for tests.

    Returns:
        The recorded request, with its money already reserved.

    Raises:
        NotFoundError: No such partner.
        ValidationError: Amount below the configured minimum, or not positive.
        ConflictError: More than the partner has available.
    """
    s = settings or get_settings()

    # Serialises concurrent requests from one partner. The reservation below is
    # what the loser then sees, but only a lock guarantees it reads *after* the
    # winner has written.
    partner = (
        await db.execute(
            select(AffiliatePartner).where(AffiliatePartner.id == partner_id).with_for_update()
        )
    ).scalar_one_or_none()
    if partner is None:
        raise NotFoundError("partner not found")

    if amount <= 0:
        raise ValidationError("amount must be positive")
    if amount < s.affiliate_min_payout:
        raise ValidationError(
            f"minimum withdrawal is {s.affiliate_min_payout} {currency}",
            extra={"minimum": str(s.affiliate_min_payout), "currency": currency},
        )

    available = await account_balance(
        db, partner_id=partner_id, kind="partner_balance", currency=currency
    )
    if amount > available:
        raise ConflictError(
            "not enough available balance",
            extra={"available": str(available), "requested": str(amount)},
        )

    payout = AffiliatePayout(
        id=new_id(),
        partner_id=partner_id,
        amount=amount,
        currency=currency,
        card_number=card_number,
        card_holder=card_holder,
        status="requested",
    )
    db.add(payout)
    await db.flush()

    await post_payout_hold(
        db,
        payout_id=payout.id,
        partner_id=partner_id,
        amount=amount,
        currency=currency,
    )
    # Amount and id only. The card is PII (CLAUDE.md §9) and this is the one
    # place in the module where it would be easiest to leak.
    log.info("affiliate.payout.requested", payout_id=payout.id, amount=str(amount))
    return payout


async def mark_paid(db: AsyncSession, *, payout_id: str, note: str | None = None) -> None:
    """Record that an admin has actually transferred the money.

    Raises:
        NotFoundError: No such payout.
        ConflictError: The request is not open.
    """
    payout = await _open_payout(db, payout_id)
    await post_payout_paid(
        db,
        payout_id=payout.id,
        partner_id=payout.partner_id,
        amount=payout.amount,
        currency=payout.currency,
    )
    payout.status = "paid"
    payout.admin_note = note
    payout.processed_at = now()
    await db.flush()
    log.info("affiliate.payout.paid", payout_id=payout.id)


async def reject_payout(db: AsyncSession, *, payout_id: str, note: str | None = None) -> None:
    """Refuse a request and return its money to the withdrawable balance.

    Raises:
        NotFoundError: No such payout.
        ConflictError: The request is not open.
    """
    payout = await _open_payout(db, payout_id)
    await post_payout_rejected(
        db,
        payout_id=payout.id,
        partner_id=payout.partner_id,
        amount=payout.amount,
        currency=payout.currency,
    )
    payout.status = "rejected"
    payout.admin_note = note
    payout.processed_at = now()
    await db.flush()
    log.info("affiliate.payout.rejected", payout_id=payout.id)


async def list_for_partner(
    db: AsyncSession, *, partner_id: str, limit: int = 50, offset: int = 0
) -> list[AffiliatePayout]:
    """This partner's withdrawal history, newest first."""
    capped = max(1, min(limit, 200))
    rows = (
        await db.execute(
            select(AffiliatePayout)
            .where(AffiliatePayout.partner_id == partner_id)
            .order_by(AffiliatePayout.created_at.desc(), AffiliatePayout.id.desc())
            .limit(capped)
            .offset(max(0, offset))
        )
    ).scalars()
    return list(rows)


async def _open_payout(db: AsyncSession, payout_id: str) -> AffiliatePayout:
    """A payout that can still be acted on, locked for the caller.

    Locked because both settling and refusing move money, and a request must
    not be paid and rejected at once by two admins with the same tab open.
    """
    payout = (
        await db.execute(
            select(AffiliatePayout).where(AffiliatePayout.id == payout_id).with_for_update()
        )
    ).scalar_one_or_none()
    if payout is None:
        raise NotFoundError("payout not found")
    if payout.status not in ("requested", "approved"):
        raise ConflictError(f"payout is already {payout.status}")
    return payout


__all__ = [
    "list_for_partner",
    "mark_paid",
    "reject_payout",
    "request_payout",
]
