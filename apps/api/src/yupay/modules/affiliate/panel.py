"""What a signed-in partner can read about themselves.

Every function here takes a ``partner_id`` that the caller got from a token,
never from a request parameter. That is the rule which keeps one partner out of
another's earnings, and it is worth stating because "list commissions for
partner X" is the natural signature and is the wrong one here.

**Balance is read from the ledger, not computed from the commissions table.**
The three-account split exists precisely so that "available to withdraw" is a
balance rather than a sum, and recomputing it here would quietly reintroduce
the second source of truth the split was built to remove.

Periods are **rolling windows**, not calendar months. Two reasons: this project
has no display-timezone convention, so a calendar month would silently be a UTC
month and read wrong for a partner in Tashkent every evening; and a rolling
figure has no cliff on the 1st where a partner's month resets to zero. The
labels shown to partners say "30 days", not "this month", so the wording
matches the arithmetic.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.modules.affiliate.models import (
    AffiliateAttribution,
    AffiliateCode,
    AffiliateCommission,
)
from yupay.modules.wallet import service as wallet_service

#: The windows a partner can ask for, and how many days each spans.
StatsPeriod = Literal["day", "week", "month", "year"]

_WINDOW_DAYS: dict[StatsPeriod, int] = {
    "day": 1,
    "week": 7,
    "month": 30,
    "year": 365,
}

#: Commission states that represent money the partner still has. `void` was
#: reversed by a refund and `paid` has already left, so neither counts as
#: earnings the panel should be adding up.
_LIVE_STATUSES = ("pending", "available", "paid")

DEFAULT_CURRENCY = "UZS"


async def account_balance(
    db: AsyncSession, *, partner_id: str, kind: str, currency: str
) -> Decimal:
    """One of a partner's ledger balances.

    Args:
        db: Session.
        partner_id: From the caller's token.
        kind: ``partner_balance``, ``partner_pending`` or
            ``partner_payout_hold``.
        currency: The account's currency.

    Returns:
        The balance, or zero when the account has never been used.
    """
    account = await wallet_service.ensure_account(
        db, owner_type="partner", owner_id=partner_id, kind=kind, currency=currency
    )
    # Annotated rather than returned bare: mypy skips analysing the wallet
    # package from here, so the call reads as Any.
    amount: Decimal = await wallet_service.balance(db, account.id)
    return amount


async def balances(
    db: AsyncSession, *, partner_id: str, currency: str = DEFAULT_CURRENCY
) -> dict[str, Decimal]:
    """Available, held and reserved, straight from the ledger.

    ``available`` is the balance of ``partner_balance`` — the single source of
    truth a payout request checks against. ``held`` is commission still inside
    its hold period. ``reserved`` is money already claimed by an open payout
    request.

    Returns:
        A mapping with keys ``available``, ``held`` and ``reserved``.
    """
    return {
        "available": await account_balance(
            db, partner_id=partner_id, kind="partner_balance", currency=currency
        ),
        "held": await account_balance(
            db, partner_id=partner_id, kind="partner_pending", currency=currency
        ),
        "reserved": await account_balance(
            db, partner_id=partner_id, kind="partner_payout_hold", currency=currency
        ),
    }


async def stats(db: AsyncSession, *, partner_id: str, period: StatsPeriod) -> dict[str, object]:
    """Earnings and activations over a rolling window.

    Args:
        db: Session.
        partner_id: From the caller's token.
        period: One of ``day``, ``week``, ``month``, ``year`` — 1, 7, 30 and
            365 days back from now. See the module docstring for why these are
            rolling rather than calendar.

    Returns:
        ``{"period", "since", "earned", "orders", "activations"}``. A partner
        with no activity reads as zeroes, not as an error.
    """
    since = now() - timedelta(days=_WINDOW_DAYS[period])

    earned, orders = (
        await db.execute(
            select(
                func.coalesce(func.sum(AffiliateCommission.amount), 0),
                func.count(AffiliateCommission.id),
            ).where(
                AffiliateCommission.partner_id == partner_id,
                AffiliateCommission.status.in_(_LIVE_STATUSES),
                AffiliateCommission.created_at >= since,
            )
        )
    ).one()

    activations = await db.scalar(
        select(func.count(AffiliateAttribution.id)).where(
            AffiliateAttribution.partner_id == partner_id,
            AffiliateAttribution.created_at >= since,
        )
    )

    return {
        "period": period,
        "since": since,
        "earned": Decimal(earned),
        "orders": int(orders),
        "activations": int(activations or 0),
    }


async def codes(db: AsyncSession, *, partner_id: str) -> list[AffiliateCode]:
    """Every code this partner owns, newest first."""
    rows = (
        await db.execute(
            select(AffiliateCode)
            .where(AffiliateCode.partner_id == partner_id)
            .order_by(AffiliateCode.created_at.desc())
        )
    ).scalars()
    return list(rows)


async def commissions(
    db: AsyncSession, *, partner_id: str, limit: int = 50, offset: int = 0
) -> tuple[list[AffiliateCommission], int]:
    """One page of this partner's commissions, newest first.

    Returns:
        ``(rows, total)`` — the page and the unpaged count, so the panel can
        show how many there are without fetching them all.
    """
    capped = max(1, min(limit, 200))
    total = await db.scalar(
        select(func.count(AffiliateCommission.id)).where(
            AffiliateCommission.partner_id == partner_id
        )
    )
    rows = (
        await db.execute(
            select(AffiliateCommission)
            .where(AffiliateCommission.partner_id == partner_id)
            # `created_at` defaults to CURRENT_TIMESTAMP, which in Postgres is
            # the transaction start, so a sweep pass writes many rows sharing
            # one value. The id breaks the tie — new_id() is UUIDv7, so id
            # order is insertion order — without which rows duplicate and
            # vanish across pages under OFFSET.
            .order_by(AffiliateCommission.created_at.desc(), AffiliateCommission.id.desc())
            .limit(capped)
            .offset(max(0, offset))
        )
    ).scalars()
    return list(rows), int(total or 0)


__all__ = [
    "DEFAULT_CURRENCY",
    "StatsPeriod",
    "account_balance",
    "balances",
    "codes",
    "commissions",
    "stats",
]
