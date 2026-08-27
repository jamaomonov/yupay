"""Every ledger posting the affiliate program makes, and nothing else.

Kept apart from the query logic in ``accrual`` on purpose: these few lines of
bookkeeping are the part a reviewer must read most carefully, and a short file
is one you can hold in your head at once.

The postings mirror the shape ``promo.redeem`` already uses
(``D user_wallet / C house_promo_expense``), so no new rules enter double-entry
bookkeeping here.

Reaches into ``wallet.service`` rather than ``wallet.api``. The facade imports
the wallet router, which pulls in the whole v1 route stack and circles straight
back — an ImportError for any caller that is not already inside the app. The
scheduler imports this module, and a scheduler process has no business loading
FastAPI routes. The existing ``purge_sessions`` and ``purge_evidence`` jobs
reach past their facades for the same reason.

Idempotency keys are derived from the commission row's id rather than random,
so a retry after a timeout replays the original posting instead of making a
second one — ``wallet.service.post`` returns the existing transaction for a key
it has already seen.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.wallet import service as wallet_service

#: Smallest payable unit per currency. UZS has no subunit in practice — Payme
#: and Click both reject fractions — so commission is whole sums.
_QUANTUM: dict[str, Decimal] = {"UZS": Decimal("1")}
_DEFAULT_QUANTUM = Decimal("0.01")

_HOUSE_OWNER = "house"


def commission_amount(total: Decimal, percent: Decimal, currency: str) -> Decimal:
    """Commission on ``total`` at ``percent``, rounded to a payable amount.

    Args:
        total: The order total the buyer actually paid, after any discount.
        percent: The code's commission percentage, e.g. ``Decimal("2")``.
        currency: ISO-4217 code, used to pick the rounding quantum.

    Returns:
        The commission, quantized to the currency's smallest payable unit.
    """
    quantum = _QUANTUM.get(currency.upper(), _DEFAULT_QUANTUM)
    return (total * percent / Decimal(100)).quantize(quantum, rounding=ROUND_HALF_UP)


async def _partner_account(db: AsyncSession, *, partner_id: str, kind: str, currency: str) -> str:
    account = await wallet_service.ensure_account(
        db, owner_type="partner", owner_id=partner_id, kind=kind, currency=currency
    )
    return account.id


async def _house_account(db: AsyncSession, *, kind: str, currency: str) -> str:
    account = await wallet_service.ensure_account(
        db, owner_type=_HOUSE_OWNER, owner_id=_HOUSE_OWNER, kind=kind, currency=currency
    )
    return account.id


async def post_accrual(
    db: AsyncSession,
    *,
    commission_id: str,
    partner_id: str,
    amount: Decimal,
    currency: str,
    order_id: str,
) -> None:
    """Book earned commission: ``D partner_pending / C house_affiliate_expense``.

    Args:
        db: Session. The caller owns the transaction.
        commission_id: The ``affiliate_commissions`` row this posting belongs
            to; it is also the idempotency key.
        partner_id: Who earned it.
        amount: The commission, already rounded.
        currency: The order's currency.
        order_id: Recorded as the transaction's reference, for the audit trail.
    """
    pending = await _partner_account(
        db, partner_id=partner_id, kind="partner_pending", currency=currency
    )
    expense = await _house_account(db, kind="house_affiliate_expense", currency=currency)
    await wallet_service.post(
        db,
        kind="affiliate.accrue",
        legs=[
            wallet_service.Leg(account_id=pending, direction="D", amount=amount, currency=currency),
            wallet_service.Leg(account_id=expense, direction="C", amount=amount, currency=currency),
        ],
        idempotency_key=f"affiliate.accrue:{commission_id}",
        reference=wallet_service.Reference(type="order", id=order_id),
        actor="scheduler",
    )


async def post_maturation(
    db: AsyncSession,
    *,
    commission_id: str,
    partner_id: str,
    amount: Decimal,
    currency: str,
) -> None:
    """Release held commission: ``D partner_balance / C partner_pending``.

    Both accounts belong to the partner, so this moves nothing in or out of the
    business — it only changes what the partner is allowed to withdraw.

    Args:
        db: Session. The caller owns the transaction.
        commission_id: The row being released; also the idempotency key.
        partner_id: Whose money it is.
        amount: The commission, as accrued.
        currency: The commission's currency.
    """
    pending = await _partner_account(
        db, partner_id=partner_id, kind="partner_pending", currency=currency
    )
    balance = await _partner_account(
        db, partner_id=partner_id, kind="partner_balance", currency=currency
    )
    await wallet_service.post(
        db,
        kind="affiliate.mature",
        legs=[
            wallet_service.Leg(account_id=balance, direction="D", amount=amount, currency=currency),
            wallet_service.Leg(account_id=pending, direction="C", amount=amount, currency=currency),
        ],
        idempotency_key=f"affiliate.mature:{commission_id}",
        actor="scheduler",
    )


__all__ = ["commission_amount", "post_accrual", "post_maturation"]
