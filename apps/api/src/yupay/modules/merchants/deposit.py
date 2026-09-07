"""The merchant USD deposit ledger — every movement of a reseller's prepaid balance.

The deposit is a **ledger balance, never a column**: ``merchant_deposit`` is
debit-normal exactly like ``user_wallet``, and every movement goes through
``wallet.service.post`` so idempotency-by-key and all-or-nothing legs are
inherited rather than rebuilt. The full posting table — the authoritative one,
which no caller may re-derive directions from — lives in this module's README.

Split out of ``service.py`` (Task 5): accounts, machine credentials and money
are three responsibilities, and money is the one that has to be readable on
its own. ``service.py`` keeps the account, ``credentials.py`` the key
lifecycle, and everything that moves or reads a balance is here — including
the grouped ledger listing, which M1 first wrote in ``admin.py`` and which
both the admin surface and ``/merchant/v1/transactions`` now read from one
place.

Reaches into ``wallet.service`` rather than the ``wallet.api`` facade for the
same reason ``affiliate/ledger.py`` does: the facade imports the wallet
router, which pulls in the whole v1 route stack and circles straight back —
an ImportError for any caller that is not already inside the app.

Freezing a merchant (``service.set_status``) blocks ORDERS, never money in:
support can always credit a frozen merchant's deposit, e.g. to settle a
dispute while the account is under review.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import case, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.errors import ConflictError, ValidationError
from yupay.modules.merchants import webhooks
from yupay.modules.merchants.service import get_merchant
from yupay.modules.wallet import service as wallet_service
from yupay.modules.wallet.models import WalletAccount, WalletPosting, WalletTransaction

#: The deposit is USD-only in v1 (spec §7): merchants settle invoices in USD
#: and every SKU already carries a USD cost basis. A second currency would be
#: a new account row per merchant, not a schema change.
DEPOSIT_CURRENCY = "USD"

_HOUSE_OWNER = "house"
_CENT = Decimal("0.01")

#: RFC 7807 ``code`` for an order the deposit cannot cover (spec §9.4). Lives
#: here, beside the guard that raises it, so the machine API and the ledger
#: cannot spell it differently.
INSUFFICIENT_DEPOSIT_CODE = "insufficient_deposit"


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

    A fresh credit also enqueues ``balance.credited`` (spec §10), in this same
    transaction. A **replay** does not: it books nothing, and announcing money
    that did not move would have a reseller crediting their own end customer
    twice. The check is a read taken before the posting, because ``post()``
    gives its caller no way to tell a replay from a fresh write afterwards; two
    genuinely concurrent credits under one key can therefore both miss it and
    both announce, which is the at-least-once delivery a webhook receiver has
    to be built for regardless.

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
    await get_merchant(db, merchant_id)

    # Read *before* posting, because ``post()`` answers a replay with the
    # original transaction and gives the caller no way to tell the two apart
    # afterwards. A replay books nothing, so it must announce nothing: a
    # ``balance.credited`` for money that did not move would have a reseller
    # crediting their own customer twice.
    replayed = (
        await db.execute(
            select(WalletTransaction.id).where(WalletTransaction.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none() is not None

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
    txn = await wallet_service.post(
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
    if not replayed:
        # In this transaction, with the credit, so a merchant is told about
        # money that is committed or about nothing at all.
        await webhooks.on_balance_credited(
            db,
            merchant_id=merchant_id,
            amount=amount,
            balance=await deposit_balance(db, merchant_id=merchant_id),
        )
    return txn


async def charge_deposit(
    db: AsyncSession,
    *,
    merchant_id: str,
    amount: Decimal,
    order_id: str,
) -> WalletTransaction:
    """Debit a merchant's deposit for an order: ``C merchant_deposit / D house_payments_received``.

    The exact mirror of :func:`credit_deposit`'s legs — the module README's
    posting table is authoritative and the directions are not re-derived here.
    ``merchant_deposit`` is debit-normal, so a credit posting lowers the
    balance; the house counter takes the matching debit, which is the same
    ``house_payments_received`` bucket the prepayment landed in, now being
    drawn down against goods.

    **This is the authoritative overdraw guard**, not the caller's early
    check. The deposit account row is locked with ``SELECT … FOR UPDATE``
    before the balance is read, so two concurrent orders serialise here rather
    than both reading the same pre-spend balance and both passing — the same
    shape ``wallet.service.reverse_topup`` uses for a user wallet. The caller's
    earlier read exists only to answer with a clean ``409`` before any row is
    written; it is a courtesy, and this is the invariant.

    Idempotent on ``order_id``: the ledger key is derived from it, and an
    order id is unique per ``(merchant, merchant_order_id)`` by
    ``uq_orders_idem_merchant``. So even a caller that reached this twice for
    one order would replay the first transaction rather than debit twice —
    there is no non-idempotent side path on the merchant order flow.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose deposit to draw on. Must exist.
        amount: Positive USD amount — the price the order charges.
        order_id: The order being paid for; the ledger reference and the
            replay handle.

    Returns:
        The ledger transaction (the existing one on replay).

    Raises:
        ValidationError: If ``amount`` is not positive.
        NotFoundError: If no merchant with that id exists.
        ConflictError: If the deposit cannot cover ``amount``.
    """
    if amount <= 0:
        raise ValidationError("deposit charge must be positive", extra={"amount": str(amount)})
    await get_merchant(db, merchant_id)

    deposit = await wallet_service.ensure_account(
        db,
        owner_type="merchant",
        owner_id=merchant_id,
        kind="merchant_deposit",
        currency=DEPOSIT_CURRENCY,
    )
    locked = (
        await db.execute(
            select(WalletAccount).where(WalletAccount.id == deposit.id).with_for_update()
        )
    ).scalar_one()
    have = await wallet_service.balance(db, locked.id)
    if have < amount:
        raise ConflictError(
            "deposit balance does not cover this order",
            code=INSUFFICIENT_DEPOSIT_CODE,
            balance_usd=str(have.quantize(_CENT, rounding=ROUND_DOWN)),
            required_usd=str(amount),
        )
    received = await wallet_service.ensure_account(
        db,
        owner_type=_HOUSE_OWNER,
        owner_id=_HOUSE_OWNER,
        kind="house_payments_received",
        currency=DEPOSIT_CURRENCY,
    )
    return await wallet_service.post(
        db,
        kind="merchant_order_charge",
        legs=[
            # C on merchant_deposit (NORMAL=D) → balance ↓ by ``amount``.
            wallet_service.Leg(
                account_id=deposit.id,
                direction="C",
                amount=amount,
                currency=DEPOSIT_CURRENCY,
            ),
            # D on the house counter (NORMAL=D) → SUM(D) == SUM(C) holds.
            wallet_service.Leg(
                account_id=received.id,
                direction="D",
                amount=amount,
                currency=DEPOSIT_CURRENCY,
            ),
        ],
        idempotency_key=f"merchant-order:{order_id}",
        reference=wallet_service.Reference(type="order", id=order_id),
        actor=f"merchant:{merchant_id}",
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


async def list_deposit_transactions(
    db: AsyncSession,
    *,
    merchant_id: str,
    limit: int = 50,
    before: tuple[datetime, str] | None = None,
) -> list[tuple[WalletTransaction, Decimal]]:
    """A merchant's deposit ledger, newest first, with the signed delta.

    One grouped query: every transaction that touched the merchant's
    ``merchant_deposit`` account, with the normal-side-signed SUM of its
    merchant-side postings — i.e. how much this transaction moved the deposit
    balance (positive = up). Order-charge rows surface here with a negative
    delta and M3's refunds with a positive one, without any change.

    Written for M1's admin ledger panel and **shared** with
    ``/merchant/v1/transactions`` (``transactions.py``) rather than copied: a
    second grouped sum over the same postings is a second chance to get a
    direction backwards, and the two surfaces must never disagree about what a
    merchant's ledger says.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose ledger to read. Must exist.
        limit: Newest-first cap; the caller bounds it.
        before: Keyset anchor — return only rows strictly older than this
            ``(created_at, transaction_id)`` pair, in the same
            ``created_at DESC, id DESC`` order the listing already used.
            ``None`` starts at the newest row. The admin panel does not use
            it; see ``transactions.py`` for why the machine API pages this way
            and not by OFFSET.

    Returns:
        ``(transaction, signed_amount)`` pairs, newest first.

    Raises:
        NotFoundError: If no merchant with that id exists — an empty ledger
            for a typo'd id must be a 404, never a plausible-looking ``[]``.
    """
    await get_merchant(db, merchant_id)
    normal = wallet_service.NORMAL_SIDE["merchant_deposit"]
    signed_sum = func.sum(
        case(
            (WalletPosting.direction == normal, WalletPosting.amount),
            else_=-WalletPosting.amount,
        )
    )
    stmt = (
        select(WalletTransaction, signed_sum)
        .join(WalletPosting, WalletPosting.transaction_id == WalletTransaction.id)
        .join(WalletAccount, WalletAccount.id == WalletPosting.account_id)
        .where(
            WalletAccount.owner_type == "merchant",
            WalletAccount.owner_id == merchant_id,
            WalletAccount.kind == "merchant_deposit",
            WalletAccount.currency == DEPOSIT_CURRENCY,
        )
    )
    if before is not None:
        # A row-value comparison, not ``created_at < x OR (created_at = x AND
        # id < y)``: one expression that matches the ORDER BY below exactly, so
        # no row can fall on both sides of a page boundary.
        # Compared against the plain Python tuple, not a second ``tuple_()``:
        # SQLAlchemy takes each bind parameter's type from the matching column
        # on the left, so the ``id`` half binds as a UUID rather than as text —
        # which Postgres has no ``<`` for.
        stmt = stmt.where(tuple_(WalletTransaction.created_at, WalletTransaction.id) < before)
    stmt = (
        # PK grouping — Postgres derives the other transaction columns from it.
        stmt.group_by(WalletTransaction.id)
        # ``created_at`` is transaction-start time, so same-instant rows are
        # possible; the UUIDv7 id is the monotonic tiebreak. The pair is unique
        # (``id`` is the primary key), which is what makes it usable as a
        # keyset cursor.
        .order_by(WalletTransaction.created_at.desc(), WalletTransaction.id.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [(txn, Decimal(amount)) for txn, amount in rows]


async def refunded_for_order(db: AsyncSession, *, merchant_id: str, order_id: str) -> Decimal:
    """How much of one order has been credited back to this merchant's deposit.

    The sum of the **debit** legs on the merchant's ``merchant_deposit``
    account across every ledger transaction referencing this order —
    ``merchant_deposit`` is debit-normal, so a debit is money returning. The
    charge itself is a credit and is therefore not counted, which is why this
    reads a direction rather than a transaction kind: it does not have to know
    the name M3 will give a refund.

    Today it always returns zero, because **nothing refunds a merchant order
    yet** (the module README's posting table marks that row *not implemented*).
    It is computed rather than hardcoded so the field on
    ``GET /merchant/v1/orders/{id}`` starts telling the truth the moment M3
    posts the row, with no change here and no change to the contract.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The owning merchant — the account scope.
        order_id: The order whose ledger reference to sum.

    Returns:
        The amount returned to the deposit for this order; ``Decimal("0")``
        when nothing has been.
    """
    normal = wallet_service.NORMAL_SIDE["merchant_deposit"]
    stmt = (
        select(func.coalesce(func.sum(WalletPosting.amount), Decimal("0")))
        .join(WalletAccount, WalletAccount.id == WalletPosting.account_id)
        .join(WalletTransaction, WalletTransaction.id == WalletPosting.transaction_id)
        .where(
            WalletAccount.owner_type == "merchant",
            WalletAccount.owner_id == merchant_id,
            WalletAccount.kind == "merchant_deposit",
            WalletAccount.currency == DEPOSIT_CURRENCY,
            WalletPosting.direction == normal,
            WalletTransaction.reference_type == "order",
            WalletTransaction.reference_id == order_id,
        )
    )
    return Decimal((await db.execute(stmt)).scalar_one())


__all__ = [
    "DEPOSIT_CURRENCY",
    "INSUFFICIENT_DEPOSIT_CODE",
    "charge_deposit",
    "credit_deposit",
    "deposit_balance",
    "list_deposit_transactions",
    "refunded_for_order",
]
