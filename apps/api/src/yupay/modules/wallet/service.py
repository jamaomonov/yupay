"""Wallet service: ledger primitives.

This is the **only** module that writes to the ledger tables. Every other module
calls ``post(...)`` through ``wallet.api``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.modules.wallet.models import WalletAccount, WalletPosting, WalletTransaction

# Normal side of each account kind. Balance = SUM(normal_side) − SUM(other_side).
NORMAL_SIDE: dict[str, str] = {
    "user_wallet": "D",
    "user_cashback": "D",
    "user_promo_credit": "D",
    "house_cogs": "D",
    "house_promo_expense": "D",
    "house_refunds": "D",
    "house_revenue": "C",
    "house_fx_pnl": "C",
    "provider_clearing": "C",
}


@dataclass(frozen=True)
class Leg:
    """A single posting in a transaction: which account, which side, how much."""

    account_id: str
    direction: str  # 'D' | 'C'
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class Reference:
    """What this transaction is about (an order, a payment, a manual adjust, …)."""

    type: str
    id: str


def _validate_legs(legs: list[Leg]) -> None:
    if len(legs) < 2:
        raise ValidationError("a wallet transaction needs at least 2 legs")
    sums: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"D": Decimal("0"), "C": Decimal("0")}
    )
    for leg in legs:
        if leg.amount <= 0:
            raise ValidationError(
                "leg amount must be positive", extra={"amount": str(leg.amount)}
            )
        if leg.direction not in ("D", "C"):
            raise ValidationError(
                "leg direction must be D or C", extra={"direction": leg.direction}
            )
        sums[leg.currency][leg.direction] += leg.amount
    for currency, bucket in sums.items():
        if bucket["D"] != bucket["C"]:
            raise ValidationError(
                "ledger invariant break: SUM(D) ≠ SUM(C)",
                extra={
                    "currency": currency,
                    "debit": str(bucket["D"]),
                    "credit": str(bucket["C"]),
                },
            )


async def ensure_account(
    db: AsyncSession,
    *,
    owner_type: str,
    owner_id: str,
    kind: str,
    currency: str,
) -> WalletAccount:
    """Find an account by tuple, or create it. Race-safe via UNIQUE."""
    if kind not in NORMAL_SIDE:
        raise ValidationError(f"unknown account kind: {kind}")
    stmt = select(WalletAccount).where(
        WalletAccount.owner_type == owner_type,
        WalletAccount.owner_id == owner_id,
        WalletAccount.kind == kind,
        WalletAccount.currency == currency,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing
    account = WalletAccount(
        id=new_id(),
        owner_type=owner_type,
        owner_id=owner_id,
        kind=kind,
        currency=currency,
    )
    db.add(account)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return (await db.execute(stmt)).scalar_one()
    return account


async def post(
    db: AsyncSession,
    *,
    kind: str,
    legs: list[Leg],
    idempotency_key: str,
    reference: Reference | None = None,
    actor: str = "system",
    metadata: dict[str, Any] | None = None,
) -> WalletTransaction:
    """All-or-nothing ledger posting.

    Returns the existing transaction if ``idempotency_key`` was already used.
    """
    existing = (
        await db.execute(
            select(WalletTransaction)
            .options(selectinload(WalletTransaction.postings))
            .where(WalletTransaction.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    _validate_legs(legs)
    # Currency-account match check.
    account_ids = {leg.account_id for leg in legs}
    accounts = (
        await db.execute(
            select(WalletAccount).where(WalletAccount.id.in_(account_ids))
        )
    ).scalars().all()
    by_id = {a.id: a for a in accounts}
    if len(by_id) != len(account_ids):
        raise NotFoundError("one or more wallet accounts not found")
    for leg in legs:
        acc = by_id[leg.account_id]
        if acc.currency != leg.currency:
            raise ValidationError(
                "leg currency does not match account currency",
                extra={
                    "account_id": leg.account_id,
                    "account_currency": acc.currency,
                    "leg_currency": leg.currency,
                },
            )
        if acc.status != "active":
            raise ConflictError(
                "account is frozen", extra={"account_id": leg.account_id}
            )

    txn = WalletTransaction(
        id=new_id(),
        kind=kind,
        reference_type=reference.type if reference else None,
        reference_id=reference.id if reference else None,
        idempotency_key=idempotency_key,
        actor=actor,
        extra_metadata=metadata or {},
    )
    db.add(txn)
    for leg in legs:
        db.add(
            WalletPosting(
                id=new_id(),
                transaction_id=txn.id,
                account_id=leg.account_id,
                direction=leg.direction,
                amount=leg.amount,
                currency=leg.currency,
            )
        )
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        # Concurrent insert with same key — replay.
        again = (
            await db.execute(
                select(WalletTransaction)
                .options(selectinload(WalletTransaction.postings))
                .where(WalletTransaction.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if again is not None:
            return again
        raise ConflictError("wallet post failed") from exc
    await db.refresh(txn, attribute_names=["postings"])
    return txn


async def balance(db: AsyncSession, account_id: str) -> Decimal:
    """Return the signed balance of an account in its own currency.

    Sign reflects the kind: ``user_wallet`` of $10 returns ``Decimal("10")``,
    ``house_revenue`` of $10 also returns ``Decimal("10")`` (each in its normal side).
    """
    account = (
        await db.execute(select(WalletAccount).where(WalletAccount.id == account_id))
    ).scalar_one_or_none()
    if account is None:
        raise NotFoundError("wallet account not found")
    normal = NORMAL_SIDE[account.kind]
    expr = func.coalesce(
        func.sum(
            case(
                (WalletPosting.direction == normal, WalletPosting.amount),
                else_=-WalletPosting.amount,
            )
        ),
        Decimal("0"),
    )
    result = await db.execute(
        select(expr).where(WalletPosting.account_id == account_id)
    )
    return Decimal(result.scalar_one())


async def user_accounts(db: AsyncSession, user_id: str) -> list[WalletAccount]:
    stmt = (
        select(WalletAccount)
        .where(WalletAccount.owner_type == "user", WalletAccount.owner_id == user_id)
        .order_by(WalletAccount.kind, WalletAccount.currency)
    )
    return list((await db.execute(stmt)).scalars().all())


async def transactions_for_user(
    db: AsyncSession, user_id: str, *, limit: int = 50
) -> list[WalletTransaction]:
    """Return recent transactions that touched any of this user's accounts."""
    account_ids_stmt = select(WalletAccount.id).where(
        WalletAccount.owner_type == "user", WalletAccount.owner_id == user_id
    )
    account_ids = [row for row in (await db.execute(account_ids_stmt)).scalars().all()]
    if not account_ids:
        return []
    txn_id_stmt = (
        select(WalletPosting.transaction_id)
        .where(WalletPosting.account_id.in_(account_ids))
        .distinct()
    )
    txn_ids = [row for row in (await db.execute(txn_id_stmt)).scalars().all()]
    if not txn_ids:
        return []
    stmt = (
        select(WalletTransaction)
        .options(selectinload(WalletTransaction.postings))
        .where(WalletTransaction.id.in_(txn_ids))
        .order_by(WalletTransaction.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_admin_adjustments(
    db: AsyncSession,
    *,
    admin_id: str | None = None,
    limit: int = 50,
) -> list[WalletTransaction]:
    """Return recent ``admin.adjust`` ledger entries.

    ``admin_id`` filters to only the entries the given admin performed
    (matched against ``actor='admin:<id>'``). ``None`` returns every
    admin's adjustment — used by the "all admins" view.
    """
    stmt = (
        select(WalletTransaction)
        .options(selectinload(WalletTransaction.postings))
        .where(WalletTransaction.kind == "admin.adjust")
        .order_by(WalletTransaction.created_at.desc())
        .limit(limit)
    )
    if admin_id is not None:
        stmt = stmt.where(WalletTransaction.actor == f"admin:{admin_id}")
    return list((await db.execute(stmt)).scalars().all())


async def admin_adjust(
    db: AsyncSession,
    *,
    user_id: str,
    kind: str,
    currency: str,
    amount: Decimal,
    reason: str,
    idempotency_key: str,
    admin_id: str,
) -> WalletTransaction:
    """One-call helper for the admin UI. Posts against ``house_promo_expense``.

    Positive ``amount`` credits the user; negative claws back.
    """
    if amount == 0:
        raise ValidationError("amount must be non-zero")
    if kind not in ("user_wallet", "user_cashback", "user_promo_credit"):
        raise ValidationError(f"admin.adjust only operates on user-side kinds: {kind}")

    user_acc = await ensure_account(
        db, owner_type="user", owner_id=user_id, kind=kind, currency=currency
    )
    house_acc = await ensure_account(
        db,
        owner_type="house",
        owner_id="house",
        kind="house_promo_expense",
        currency=currency,
    )
    magnitude = abs(amount)
    if amount > 0:
        # Credit the user: D user_<kind> (normal-D, balance ↑), C house_promo_expense.
        # Cleaner contra modelling is deferred until cash/provider accounts exist.
        legs = [
            Leg(
                account_id=user_acc.id,
                direction="D",
                amount=magnitude,
                currency=currency,
            ),
            Leg(
                account_id=house_acc.id,
                direction="C",
                amount=magnitude,
                currency=currency,
            ),
        ]
    else:
        legs = [
            Leg(
                account_id=user_acc.id,
                direction="C",
                amount=magnitude,
                currency=currency,
            ),
            Leg(
                account_id=house_acc.id,
                direction="D",
                amount=magnitude,
                currency=currency,
            ),
        ]
    return await post(
        db,
        kind="admin.adjust",
        legs=legs,
        idempotency_key=idempotency_key,
        reference=Reference(type="manual", id=user_id),
        actor=f"admin:{admin_id}",
        metadata={"reason": reason},
    )


__all__ = [
    "Leg",
    "NORMAL_SIDE",
    "Reference",
    "admin_adjust",
    "balance",
    "ensure_account",
    "list_admin_adjustments",
    "post",
    "transactions_for_user",
    "user_accounts",
]
