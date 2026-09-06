"""Merchant accounts and the USD deposit on the double-entry ledger.

M1 scope (spec §7): support credits a merchant's prepaid deposit through the
admin surface, and the cabinet reads the balance. The deposit is a ledger
balance, never a column — ``merchant_deposit`` is debit-normal exactly like
``user_wallet``, and every movement goes through ``wallet.service.post`` so
idempotency-by-key and all-or-nothing legs are inherited, not rebuilt. The
full posting table (including the M2 rows) lives in this module's README.

Reaches into ``wallet.service`` rather than the ``wallet.api`` facade for the
same reason ``affiliate/ledger.py`` does: the facade imports the wallet
router, which pulls in the whole v1 route stack and circles straight back —
an ImportError for any caller that is not already inside the app.

Freezing a merchant (``set_status``) blocks ORDERS (an M2 concern), never
money in: support can always credit a frozen merchant's deposit, e.g. to
settle a dispute while the account is under review.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.modules.merchants.models import Merchant
from yupay.modules.wallet import service as wallet_service
from yupay.modules.wallet.models import WalletAccount, WalletTransaction

#: The deposit is USD-only in v1 (spec §7): merchants settle invoices in USD
#: and every SKU already carries a USD cost basis. A second currency would be
#: a new account row per merchant, not a schema change.
DEPOSIT_CURRENCY = "USD"

_STATUSES = ("active", "frozen")
_HOUSE_OWNER = "house"


async def _get_merchant(db: AsyncSession, merchant_id: str) -> Merchant:
    """Load a merchant row or raise.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The ``merchants.id`` to load.

    Returns:
        The merchant row.

    Raises:
        NotFoundError: If no merchant with that id exists.
    """
    merchant = (
        await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    ).scalar_one_or_none()
    if merchant is None:
        raise NotFoundError("merchant not found")
    return merchant


async def create_merchant(db: AsyncSession, *, title: str) -> Merchant:
    """Create a reseller account.

    Args:
        db: Session. The caller owns the transaction.
        title: Human-readable merchant name, non-blank.

    Returns:
        The new merchant, with server defaults (``status``, ``created_at``)
        populated.

    Raises:
        ValidationError: If ``title`` is blank.
    """
    cleaned = title.strip()
    if not cleaned:
        raise ValidationError("merchant title must not be blank")
    merchant = Merchant(id=new_id(), title=cleaned)
    db.add(merchant)
    await db.flush()
    # Pick up the server-side defaults so callers see status='active' without
    # a round-trip of their own.
    await db.refresh(merchant)
    return merchant


async def set_status(db: AsyncSession, *, merchant_id: str, status: str) -> Merchant:
    """Set a merchant's status to ``active`` or ``frozen``.

    Freezing blocks new orders (enforced by the M2 order path), not deposits —
    see the module docstring.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose status to change.
        status: One of ``active`` / ``frozen``.

    Returns:
        The updated merchant row.

    Raises:
        ValidationError: If ``status`` is not a known value.
        NotFoundError: If no merchant with that id exists.
    """
    if status not in _STATUSES:
        raise ValidationError(
            "merchant status must be 'active' or 'frozen'", extra={"status": status}
        )
    merchant = await _get_merchant(db, merchant_id)
    merchant.status = status
    await db.flush()
    return merchant


async def credit_deposit(
    db: AsyncSession,
    *,
    merchant_id: str,
    amount: Decimal,
    actor: str,
    idempotency_key: str,
    note: str | None = None,
) -> WalletTransaction:
    """Book a support-credited top-up: ``D merchant_deposit / C house_payments_received``.

    Posts through ``wallet.service.post`` with the caller's idempotency key —
    a replay with the same key returns the original transaction (``post()``
    already guarantees it), so an admin retry after a timeout cannot credit
    twice.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Who gets the money. Must exist; may be frozen.
        amount: Positive USD amount.
        actor: Who did it, e.g. ``admin:<id>`` — recorded on the transaction.
        idempotency_key: The caller's key; the replay handle.
        note: Optional free-text reason, kept in the transaction metadata.

    Returns:
        The ledger transaction (existing one on replay).

    Raises:
        ValidationError: If ``amount`` is not positive.
        NotFoundError: If no merchant with that id exists.
    """
    if amount <= 0:
        raise ValidationError("deposit credit must be positive", extra={"amount": str(amount)})
    await _get_merchant(db, merchant_id)

    deposit = await wallet_service.ensure_account(
        db,
        owner_type="merchant",
        owner_id=merchant_id,
        kind="merchant_deposit",
        currency=DEPOSIT_CURRENCY,
    )
    # Counter-account for the merchant-side debit.
    # ``house_payments_received`` (NORMAL=D) is the dedicated bucket for
    # money customers paid us directly — a merchant's bank-transferred
    # prepayment is exactly that, so no new house account is invented here.
    # See ADR-0004 for the ledger model.
    received = await wallet_service.ensure_account(
        db,
        owner_type=_HOUSE_OWNER,
        owner_id=_HOUSE_OWNER,
        kind="house_payments_received",
        currency=DEPOSIT_CURRENCY,
    )
    return await wallet_service.post(
        db,
        kind="merchant_deposit_credit",
        legs=[
            # D on merchant_deposit (NORMAL=D) → balance ↑ by ``amount``.
            wallet_service.Leg(
                account_id=deposit.id,
                direction="D",
                amount=amount,
                currency=DEPOSIT_CURRENCY,
            ),
            # C on house counter (NORMAL=D) → balanced
            # double-entry; SUM(D) == SUM(C) holds.
            wallet_service.Leg(
                account_id=received.id,
                direction="C",
                amount=amount,
                currency=DEPOSIT_CURRENCY,
            ),
        ],
        idempotency_key=idempotency_key,
        reference=wallet_service.Reference(type="merchant", id=merchant_id),
        actor=actor,
        metadata={"note": note} if note is not None else {},
    )


async def deposit_balance(db: AsyncSession, *, merchant_id: str) -> Decimal:
    """Return a merchant's USD deposit balance.

    A merchant that has never been credited — or does not exist — has no
    ``merchant_deposit`` account, and its balance is simply zero. The read
    creates nothing.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose balance to read.

    Returns:
        The deposit balance; ``Decimal("0")`` when no account exists.
    """
    stmt = select(WalletAccount.id).where(
        WalletAccount.owner_type == "merchant",
        WalletAccount.owner_id == merchant_id,
        WalletAccount.kind == "merchant_deposit",
        WalletAccount.currency == DEPOSIT_CURRENCY,
    )
    account_id = (await db.execute(stmt)).scalar_one_or_none()
    if account_id is None:
        return Decimal("0")
    return await wallet_service.balance(db, account_id)


__all__ = [
    "DEPOSIT_CURRENCY",
    "create_merchant",
    "credit_deposit",
    "deposit_balance",
    "set_status",
]
