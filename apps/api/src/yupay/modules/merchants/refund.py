"""Returning a merchant's deposit when a supplier gave our money back (M3b Task 3).

The mirror of ``deposit.charge_deposit``: ``D merchant_deposit /
C house_payments_received``, referencing the **order**, so the money lands
where the reseller looks for it — on that order's ``refunded_usd``, on their
statement, and in ``balance_usd``. The module README's posting table is
authoritative and the directions are not re-derived here.

## What fires it, and what does not

Exactly one thing: a **terminal fulfilment failure on a merchant order whose
money outcome is** :attr:`~yupay.modules.fulfillment.suppliers.MoneyOutcome.RETURNED`.
``SPENT`` and ``UNKNOWN`` never refund automatically — that is the owner's
decision and not a default to optimise, because refunding money we did not get
back is not a safe failure mode. The gate itself lives in
``fulfillment.service._settle_merchant_deposit``, which is where the failure
happens; this module owns the posting and its refusals.

## The three refusals, and why each is loud

Nothing here returns "no refund happened" quietly. A refusal is either a bug
we want to hear about or an operator's money already in flight, and both need
a human rather than silence:

- :class:`NotAMerchantOrderError` — a retail order reached the refund. There
  is no deposit to credit and the buyer's money is at an acquirer.
- :class:`MissingChargeError` — the order has no charge posting. Impossible
  today (the debit and the order row are written in one transaction), so it is
  a bug or a hand-edited database, and guessing an amount is the one thing
  that must not happen.
- :class:`AlreadySettledError` — support settled this order by hand. The two
  paths are in **different ledger-key namespaces** — the operator's key is
  ``merchant-credit:{merchant}:{whatever they typed}`` — so ``post()`` cannot
  dedupe them for us, and without this check an operator settling at 10:00 and
  the drain running at 10:05 would credit one order's deposit twice and
  publish ``refunded_usd: "2.14"`` on a ``"1.07"`` order.

The caller records a refusal, alerts ops and leaves the task reading
``RETURNED``, so the failure stays refundable by hand.

## Idempotency

The ledger key is ``merchant-order-refund:{order_id}`` and it is checked
**before** the already-settled guard, so a replay returns the original
transaction rather than tripping over the money it itself moved. Concurrency
below that is ``wallet.service.post``'s: two drainers both miss the pre-read,
both insert, and the loser resolves through the unique index into a replay.

Split out of ``deposit.py`` rather than added to it: that file was already
589 lines before this milestone, past AGENTS.md's split point, and the two
things it does — moving a balance and reading one back — are what a reviewer
of a refund needs to read *without* the machine-API listing beside them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from sqlalchemy import select

from yupay.modules.merchants import webhooks
from yupay.modules.merchants.deposit import (
    DEPOSIT_CURRENCY,
    ORDER_REFERENCE_TYPE,
    charged_for_order,
    deposit_account,
    deposit_balance,
    house_received_account,
    refunded_for_order,
)
from yupay.modules.wallet import service as wallet_service
from yupay.modules.wallet.models import WalletTransaction

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.orders.models import Order

#: Namespace of the refund's ledger key. **It must be incapable of colliding
#: with ``deposit.CHARGE_KEY_PREFIX``**: ``wallet.service.post`` replays by key
#: without comparing parameters, so a collision does not raise — it returns the
#: charge, and every caller above treats that as the refund it asked for. The
#: property that makes it safe is that neither prefix is a prefix of the other,
#: which no order id on either side can close;
#: ``tests/unit/test_merchant_refund_keys.py`` pins exactly that rather than
#: the two strings.
REFUND_KEY_PREFIX: Final = "merchant-order-refund:"

#: ``WalletTransaction.kind``. Merchant-visible: ``/merchant/v1/transactions``
#: publishes ``kind`` verbatim, and a reseller reconciling a statement is
#: entitled to tell "we returned your money" from "support credited you".
REFUND_KIND: Final = "merchant_order_refund"

#: ``WalletTransaction.actor`` — the saga, not a person and not the merchant.
REFUND_ACTOR: Final = "fulfillment"

#: ``code`` on the ``409`` an admin re-drive of a settled order answers with.
#: Named here because this module owns the fact ("money has come back on this
#: order") that both the refusal and the refund read.
CODE_DEPOSIT_ALREADY_RETURNED: Final = "deposit_already_returned"


class RefundError(Exception):
    """No refund was posted, for a reason this module models.

    The base class exists so the caller can catch *this module's* refusals
    without a bare ``except Exception`` — which on this path is how a
    six-week-old circular import stayed hidden on ``main`` (64decbd). A
    ``NameError`` or an ``ImportError`` is not one of these and must not be
    swallowed as one.
    """


class NotAMerchantOrderError(RefundError):
    """The order has no ``merchant_id``, so there is no deposit to return to."""


class MissingChargeError(RefundError):
    """The order has no charge posting; there is no authority on the amount."""


class AlreadySettledError(RefundError):
    """Money has already come back on this order by another route."""


def refund_key(order_id: str) -> str:
    """The ledger idempotency key of an order's automatic refund.

    Args:
        order_id: The order being refunded.

    Returns:
        The key :func:`refund_order` posts under.
    """
    return f"{REFUND_KEY_PREFIX}{order_id}"


async def returned_for_order(db: AsyncSession, *, merchant_id: str, order_id: str) -> Decimal:
    """How much has come back to this merchant's deposit on this order.

    A one-line delegation to ``deposit.refunded_for_order`` and deliberately
    **not** a second query: the reader that answers the merchant's own
    ``refunded_usd`` is the reader that decides whether an admin may re-drive
    the order, so the two can never disagree about whether an order has been
    settled. A second sum over the same postings is a second chance to get a
    direction backwards, which is the bug this milestone came back to fix.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The owning merchant — the account scope.
        order_id: The order.

    Returns:
        The amount returned; ``Decimal("0")`` when nothing has been.
    """
    return await refunded_for_order(db, merchant_id=merchant_id, order_id=order_id)


async def refund_order(db: AsyncSession, *, order: Order, reason: str) -> WalletTransaction:
    """Return an order's deposit charge to the merchant who paid it.

    Posts ``D merchant_deposit / C house_payments_received`` for **the amount
    the charge took**, read off the charge's own ledger transaction (ruling 5
    / :func:`~yupay.modules.merchants.deposit.charged_for_order`) rather than
    off the order line, and references the order so ``refunded_usd``,
    ``/merchant/v1/transactions`` and the admin ledger all see it with no
    change to any of them.

    **A frozen merchant is refunded like any other.** Freezing blocks new
    orders — ``merchant_auth`` answers ``403 merchant_frozen`` — and has never
    blocked money *in*; an account under review is still owed for goods we
    failed to deliver, and holding the refund would make the review a
    confiscation.

    A fresh posting also enqueues ``balance.credited`` (spec §10), in this same
    transaction, for the same reason and under the same rule as
    ``credit_deposit``: a **replay** books nothing and so announces nothing.
    Emitting it is not a new promise, it is the absence of a new silence — the
    hand settlement this replaces already emits it, and an automatic path that
    did not would quietly stop telling integrators about money that used to be
    announced. The payload stays exactly ``{amount_usd, balance_usd}``; naming
    the order in it would be a ``/merchant/v2``.

    Args:
        db: Session. The caller owns the transaction, and owns deciding what a
            refusal means — see the module docstring.
        order: The failed order. Must carry a ``merchant_id``.
        reason: Short internal label recorded on the transaction metadata.
            Not a supplier's or an operator's own words: this row is readable
            through the admin audit feed.

    Returns:
        The refund transaction — the existing one on a replay.

    Raises:
        NotAMerchantOrderError: ``order.merchant_id`` is ``None``.
        MissingChargeError: The order has no charge posting.
        AlreadySettledError: Money has already come back on this order.
    """
    merchant_id = order.merchant_id
    order_id = order.id
    if merchant_id is None:
        raise NotAMerchantOrderError(f"order {order_id} has no merchant to refund")

    key = refund_key(order_id)
    # Before the guard below, not after it: this refund's own posting is money
    # that has come back on the order, so a replay that checked first would
    # refuse itself.
    existing = (
        await db.execute(select(WalletTransaction).where(WalletTransaction.idempotency_key == key))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    charged = await charged_for_order(db, merchant_id=merchant_id, order_id=order_id)
    if charged is None:
        raise MissingChargeError(f"order {order_id} has no deposit charge to return")
    already = await returned_for_order(db, merchant_id=merchant_id, order_id=order_id)
    if already > 0:
        raise AlreadySettledError(
            f"order {order_id} already had {already} returned by another route"
        )

    deposit = await deposit_account(db, merchant_id=merchant_id)
    received = await house_received_account(db)
    txn = await wallet_service.post(
        db,
        kind=REFUND_KIND,
        legs=[
            # D on merchant_deposit (NORMAL=D) → balance ↑ by the charge.
            wallet_service.Leg(
                account_id=deposit.id,
                direction="D",
                amount=charged,
                currency=DEPOSIT_CURRENCY,
            ),
            # C on the house counter (NORMAL=D) → SUM(D) == SUM(C) holds.
            wallet_service.Leg(
                account_id=received.id,
                direction="C",
                amount=charged,
                currency=DEPOSIT_CURRENCY,
            ),
        ],
        idempotency_key=key,
        # ``ORDER_REFERENCE_TYPE``, never the literal and never a word naming
        # this posting's purpose: ``reference_type`` is a free-form
        # ``String(32)`` that nothing validates, so ``"merchant_refund"``
        # would move the money and read ``"0.00"`` on the order, silently.
        reference=wallet_service.Reference(type=ORDER_REFERENCE_TYPE, id=order_id),
        actor=REFUND_ACTOR,
        metadata={"reason": reason},
    )
    await webhooks.enqueue_balance_credited(
        db,
        merchant_id=merchant_id,
        amount=charged,
        balance=await deposit_balance(db, merchant_id=merchant_id),
    )
    return txn


__all__ = [
    "CODE_DEPOSIT_ALREADY_RETURNED",
    "REFUND_ACTOR",
    "REFUND_KEY_PREFIX",
    "REFUND_KIND",
    "AlreadySettledError",
    "MissingChargeError",
    "NotAMerchantOrderError",
    "RefundError",
    "refund_key",
    "refund_order",
    "returned_for_order",
]
