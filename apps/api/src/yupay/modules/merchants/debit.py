"""Taking money back off a merchant's deposit — the fourth movement.

The mirror of ``deposit.credit_deposit``: ``C merchant_deposit /
D house_payments_received``, referencing the **merchant**, because a debit
made by an operator is not about an order. The module README's posting table
is authoritative and the directions are not re-derived here.

## What this is for, and what it is not

An operator correcting a balance: a top-up credited in error, a test merchant
being zeroed, money returned to a reseller outside the system. It is the one
movement with no automatic trigger at all — nothing in the order path, the
fulfilment saga or the webhook drain reaches it, and nothing should. A
merchant's own spending is ``deposit.charge_deposit``, which is keyed by the
order it pays for and refuses to leave that order unattributed.

It is deliberately **not** a refund. ``refund.refund_order`` returns an
order's charge and shows up on that order's ``refunded_usd``; this touches no
order and shows up only on the balance and the statement.

## The floor is zero, and it is enforced here

A deposit is prepaid money, so a debit may not take it negative: a negative
balance is a debt we have no mechanism to collect and no endpoint that can
explain it. The guard is ``charge_deposit``'s, in the same shape and for the
same reason — the account row is locked with ``SELECT … FOR UPDATE`` before
the balance is read, so a debit and a concurrent order charge serialise
instead of both reading the same pre-spend balance. It answers
``409 insufficient_deposit``, the code the order path already publishes for
"the deposit cannot cover this", because it means exactly that here too.

## No webhook, and that is a decision

A credit enqueues ``balance.credited`` (spec §10). This enqueues nothing:
there is no ``balance.debited`` in the published event set, and inventing one
would deliver an event type to integrators whose receivers were written
against a table of two. The movement is not invisible — it is on
``/merchant/v1/transactions`` with its own ``kind`` the moment it posts, which
is where a reseller reconciles a statement. Announcing it is a
``/merchant/v2`` decision, and the operator taking money off a balance is a
person who can say so directly in the meantime.

## Idempotency

The ledger key is ``merchant-debit:{merchant_id}:{the operator's key}``. That
namespace **cannot collide** with the other three: ``merchant-credit:``,
``merchant-order:`` and ``merchant-order-refund:`` all differ from it inside
the first ten characters, so no merchant id or order id on either side can
close the gap. The property matters because ``wallet.service.post`` replays by
key *without comparing parameters* — a collision would not raise, it would
hand the caller somebody else's transaction and call it a debit.

Split out of ``deposit.py`` rather than added to it, for the reason
``refund.py`` was: that file is past AGENTS.md's split point, and a reviewer
of a movement that takes money off a balance should be able to read it without
the machine-API listing beside them.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING, Final

from sqlalchemy import select

from yupay.core.errors import ConflictError, ValidationError
from yupay.modules.merchants.deposit import (
    DEPOSIT_CURRENCY,
    INSUFFICIENT_DEPOSIT_CODE,
    MERCHANT_REFERENCE_TYPE,
    NOTE_VISIBLE_KEY,
    OPERATOR_NOTE_KEY,
    deposit_account,
    house_received_account,
)
from yupay.modules.merchants.service import get_merchant
from yupay.modules.wallet import service as wallet_service
from yupay.modules.wallet.models import WalletAccount, WalletTransaction

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

#: Namespace of the debit's ledger key — see the module docstring on why it
#: cannot collide with the other three. ``tests/unit/test_merchant_debit_keys.py``
#: pins the property rather than the strings.
DEBIT_KEY_PREFIX: Final = "merchant-debit:"

#: ``WalletTransaction.kind``. Merchant-visible: ``/merchant/v1/transactions``
#: publishes ``kind`` verbatim, and a reseller reconciling a statement is
#: entitled to tell "support took this back" from "you spent it on an order".
DEBIT_KIND: Final = "merchant_deposit_debit"

_CENT = Decimal("0.01")


def debit_key(merchant_id: str, client_key: str) -> str:
    """The ledger idempotency key of an operator's deposit debit.

    Args:
        merchant_id: Whose deposit is being drawn down.
        client_key: The operator's own ``Idempotency-Key``.

    Returns:
        The key :func:`debit_deposit` posts under.
    """
    return f"{DEBIT_KEY_PREFIX}{merchant_id}:{client_key}"


async def debit_deposit(
    db: AsyncSession,
    *,
    merchant_id: str,
    amount: Decimal,
    actor: str,
    idempotency_key: str,
    reason: str,
) -> WalletTransaction:
    """Take ``amount`` off a merchant's deposit: ``C merchant_deposit / D house_payments_received``.

    Posts through ``wallet.service.post`` with the caller's key, so an
    operator's retry after a timeout replays the original transaction instead
    of debiting twice. The replay is by key and does **not** compare
    parameters: a reused key with an amended amount returns the old
    transaction and books nothing, which is why the route echoes the posted
    amount back rather than the request's.

    **A frozen merchant may be debited**, the mirror of the rule that lets
    support credit one. Freezing blocks orders, never the ledger; an account
    under review is exactly the one whose balance an operator is likely to be
    correcting.

    ``reason`` is required and not defaulted. This is the only movement whose
    whole justification is outside the system — no order, no supplier outcome,
    no payment — so the row's own metadata is the only place the "why" can
    live, and it is read back through the admin audit feed.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose deposit to draw down. Must exist.
        amount: Positive USD amount. May not exceed the balance.
        actor: Who did it, e.g. ``admin:<id>`` — recorded on the transaction.
        idempotency_key: The caller's key, already namespaced by the route
            through :func:`debit_key`; the replay handle.
        reason: Short internal label recorded on the transaction metadata.
            Readable through the admin audit feed, so not a customer's words.

    Returns:
        The debit transaction — the existing one on a replay.

    Raises:
        ValidationError: If ``amount`` is not positive, or ``reason`` is blank.
        NotFoundError: If no merchant with that id exists.
        ConflictError: If the deposit does not cover ``amount``.
    """
    if amount <= 0:
        raise ValidationError("deposit debit must be positive", extra={"amount": str(amount)})
    if not reason.strip():
        raise ValidationError("deposit debit must carry a reason")
    await get_merchant(db, merchant_id)

    deposit = await deposit_account(db, merchant_id=merchant_id)
    # The authoritative floor, in ``charge_deposit``'s shape: lock the row,
    # then read. Without the lock a debit and a concurrent order charge both
    # read the same pre-spend balance and both pass, and the deposit ends up
    # negative — the one state this account kind may never reach.
    locked = (
        await db.execute(
            select(WalletAccount).where(WalletAccount.id == deposit.id).with_for_update()
        )
    ).scalar_one()
    have = await wallet_service.balance(db, locked.id)
    if have < amount:
        raise ConflictError(
            "deposit balance does not cover this debit",
            code=INSUFFICIENT_DEPOSIT_CODE,
            balance_usd=str(have.quantize(_CENT, rounding=ROUND_DOWN)),
            required_usd=str(amount),
        )
    received = await house_received_account(db)
    return await wallet_service.post(
        db,
        kind=DEBIT_KIND,
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
        idempotency_key=idempotency_key,
        # ``MERCHANT_REFERENCE_TYPE``, never ``order``: this movement is about
        # the account, and pointing it at an order would put it on that
        # order's ``refunded_usd`` — money the merchant never got back.
        reference=wallet_service.Reference(type=MERCHANT_REFERENCE_TYPE, id=merchant_id),
        actor=actor,
        # ``OPERATOR_NOTE_KEY``, never the literal: the admin ledger reads
        # an operator's text back under that one word, and a debit whose
        # reason landed under another key would show a blank line in the
        # audit trail — the justification gone, silently.
        # ``NOTE_VISIBLE_KEY``: the reseller sees this line as an unexplained
        # negative number otherwise, and the reason was written to answer
        # exactly the question they would open a ticket to ask.
        metadata={OPERATOR_NOTE_KEY: reason, NOTE_VISIBLE_KEY: True},
    )


__all__ = [
    "DEBIT_KEY_PREFIX",
    "DEBIT_KIND",
    "debit_deposit",
    "debit_key",
]
