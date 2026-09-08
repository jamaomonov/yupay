"""The merchant USD deposit ledger — the accounts, the reads, and two of three movements.

The deposit is a **ledger balance, never a column**: ``merchant_deposit`` is
debit-normal exactly like ``user_wallet``, and every movement goes through
``wallet.service.post`` so idempotency-by-key and all-or-nothing legs are
inherited rather than rebuilt. The full posting table — the authoritative one,
which no caller may re-derive directions from — lives in this module's README.

Split out of ``service.py`` (Task 5): accounts, machine credentials and money
are three responsibilities, and money is the one that has to be readable on
its own. ``service.py`` keeps the account, ``credentials.py`` the key
lifecycle, and the accounts, every read of a balance and the two movements a
person or an order causes are here — including the grouped ledger listing,
which M1 first wrote in ``admin.py`` and which both the admin surface and
``/merchant/v1/transactions`` now read from one place.

The **third** movement is not here. M3b Task 3's automatic refund lives in
``refund.py``: this file was already past AGENTS.md's split point before it,
and a reviewer of a refund should be able to read it without the machine-API
listing beside them. The posting table in the module README is authoritative
for all three.

Reaches into ``wallet.service`` rather than the ``wallet.api`` facade for the
same reason ``affiliate/ledger.py`` does: the facade imports the wallet
router, which pulls in the whole v1 route stack and circles straight back —
an ImportError for any caller that is not already inside the app.

Freezing a merchant (``service.set_status``) blocks ORDERS, never money in:
support can always credit a frozen merchant's deposit, e.g. to settle a
dispute while the account is under review.

**A movement may name the order it belongs to.** The charge always has (its
reference is how ``/transactions`` shows a reseller which of their orders spent
what); since M3b Task 2 a credit may, which is what lets a hand settlement show
up on the failed order's ``refunded_usd`` instead of only on the balance. Both
directions spell that reference through one constant,
:data:`ORDER_REFERENCE_TYPE`, because the writer and the reader disagreeing
about the word is exactly the defect this milestone came back to fix.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import case, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.modules.merchants import webhooks
from yupay.modules.merchants.service import get_merchant
from yupay.modules.orders.models import Order
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

#: ``WalletTransaction.reference_type`` for a movement that belongs to one
#: order, and the **one** place that word is spelled.
#:
#: This constant is the defect M2 left behind, made unrepeatable. Every
#: movement of a deposit is written by one of the two functions below and read
#: back by :func:`refunded_for_order` and by ``transactions.build``; while the
#: writer and the reader each carried their own literal, ``credit_deposit``
#: could write ``"merchant"`` where the reader filtered ``"order"`` and the
#: only symptom was a field that answered ``"0.00"`` forever. A mismatch here
#: is now a NameError, not a silent zero.
ORDER_REFERENCE_TYPE: Final = "order"

#: ``reference_type`` for a movement that belongs to the merchant at large —
#: an ordinary prepayment, which settles no particular order.
MERCHANT_REFERENCE_TYPE: Final = "merchant"

#: RFC 7807 ``code`` for an ``order_id`` this merchant has no order under.
#: One refusal whether the order belongs to another merchant or never existed
#: at all — see :func:`_resolve_order_reference`. ``order_status`` re-exports
#: it as the machine API's published code for the same fact, so the two
#: order-scoped refusals in this module are one word.
CODE_ORDER_NOT_FOUND: Final = "order_not_found"

#: RFC 7807 ``code`` for a settlement that would take an order past what it
#: charged. See :func:`credit_deposit`.
CODE_ORDER_ALREADY_SETTLED: Final = "order_already_settled"

#: Namespace of the ledger key an order charge is keyed by. Spelled once, and
#: read back by :func:`charge_key` and by ``refund.refund_key``'s disjointness
#: proof — the refund's key family must be incapable of colliding with this
#: one, because ``wallet.service.post`` replays by key **without comparing
#: parameters** and a collision would silently return the charge.
CHARGE_KEY_PREFIX: Final = "merchant-order:"


def charge_key(order_id: str) -> str:
    """The ledger idempotency key of an order's deposit charge.

    A function rather than an f-string at the call site because two things now
    need it: :func:`charge_deposit`, which writes it, and
    :func:`charged_for_order`, which finds the charge back to answer "what did
    we actually take from this merchant for this order?".

    Args:
        order_id: The order the charge belongs to.

    Returns:
        The key ``charge_deposit`` posts under.
    """
    return f"{CHARGE_KEY_PREFIX}{order_id}"


def order_reference_of(txn: WalletTransaction) -> str | None:
    """The order a ledger transaction belongs to, or ``None`` if it names none.

    One reader for the one reference shape, so every surface that answers
    "which order is this row about?" — the admin credit response and
    ``transactions.build``'s statement — answers it the same way. Split out
    when the credit gained a reference: two spellings of this two-line check
    is how one of them starts disagreeing.

    Args:
        txn: Any ledger transaction.

    Returns:
        The order id, or ``None`` for a movement that settles no order.
    """
    if txn.reference_type != ORDER_REFERENCE_TYPE:
        return None
    return txn.reference_id


def _no_such_order() -> NotFoundError:
    """The single refusal for an ``order_id`` this merchant cannot be credited for.

    **One error object for three causes** — the order belongs to another
    merchant, the order does not exist, or the id is not a UUID at all — built
    in one place so the three cannot drift apart into an oracle. The rule is
    ``/merchant/v1``'s: a distinguishable "not yours" lets a caller walk a
    competitor's order numbering. Support already has an order lookup and
    loses nothing by it; what the discipline buys is that this guard stays
    correct when M4's cabinet reaches the same function from a surface where a
    merchant, not an operator, chose the id.

    It is a 404 and not a 422 for the reason ``order_status._STORABLE_ID``
    gives: an id that could not be an order id is an order that is not there,
    and spelling that as a second status would put the shape of the id back
    into the answer.
    """
    return NotFoundError("no order of this merchant's under that id", code=CODE_ORDER_NOT_FOUND)


async def _resolve_order_reference(
    db: AsyncSession, *, merchant_id: str, order_id: str
) -> wallet_service.Reference:
    """Check that ``order_id`` is this merchant's order, and reference it.

    Two things happen here and both are load-bearing.

    **The id is canonicalised before it is compared.** ``orders.id`` is a
    Postgres ``uuid`` column, so a string that is not a UUID reaches it as a
    ``DataError`` and comes back a bare 500 — the class of bug
    ``machine_schemas._canonical_uuid`` was written for, and ``{braced}`` is
    what ``Guid.ToString("B")`` produces. Canonical form is also what gets
    **stored**: ``reference_id`` is a ``VARCHAR``, so an undashed or braced
    spelling would save happily and then match nothing, leaving
    ``refunded_usd`` at ``"0.00"`` — this task's own defect, re-introduced one
    layer down.

    **The scope is the merchant.** A credit naming somebody else's order is
    refused exactly like one naming an order that never existed; see
    :func:`_no_such_order`.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The merchant being credited — the scope.
        order_id: The order to attribute the credit to, in any UUID spelling.

    Returns:
        The ledger reference to post with.

    Raises:
        NotFoundError: ``order_not_found``.
    """
    try:
        canonical = str(UUID(order_id))
    except ValueError as exc:
        raise _no_such_order() from exc
    found = (
        await db.execute(
            select(Order.id).where(Order.id == canonical, Order.merchant_id == merchant_id)
        )
    ).scalar_one_or_none()
    if found is None:
        raise _no_such_order()
    return wallet_service.Reference(type=ORDER_REFERENCE_TYPE, id=canonical)


async def deposit_account(db: AsyncSession, *, merchant_id: str) -> WalletAccount:
    """The merchant's ``merchant_deposit`` account, created if it is the first movement.

    One definition of the owner/kind/currency tuple, shared by the three
    functions that move a deposit. Four copies of the same ``ensure_account``
    call is four chances for one of them to name a different account and post
    a leg nobody's balance can see.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose deposit.

    Returns:
        The account row.
    """
    return await wallet_service.ensure_account(
        db,
        owner_type="merchant",
        owner_id=merchant_id,
        kind="merchant_deposit",
        currency=DEPOSIT_CURRENCY,
    )


async def house_received_account(db: AsyncSession) -> WalletAccount:
    """The house counter-account every deposit movement balances against.

    ``house_payments_received`` (NORMAL=D) is the dedicated bucket for money
    customers paid us directly — a merchant's bank-transferred prepayment is
    exactly that, drawn down against goods by a charge and put back by a
    refund. No new house account is invented for the refund; see ADR-0004 for
    the ledger model.

    Args:
        db: Session. The caller owns the transaction.

    Returns:
        The account row.
    """
    return await wallet_service.ensure_account(
        db,
        owner_type=_HOUSE_OWNER,
        owner_id=_HOUSE_OWNER,
        kind="house_payments_received",
        currency=DEPOSIT_CURRENCY,
    )


async def credit_deposit(
    db: AsyncSession,
    *,
    merchant_id: str,
    amount: Decimal,
    actor: str,
    idempotency_key: str,
    order_id: str | None,
    note: str | None = None,
) -> WalletTransaction:
    """Book a support-credited top-up: ``D merchant_deposit / C house_payments_received``.

    Posts through ``wallet.service.post`` with the caller's idempotency key —
    a replay with the same key returns the original transaction (``post()``
    already guarantees it), so an admin retry after a timeout cannot credit
    twice.

    ``order_id`` names the order this credit settles, and is the whole of M3b
    Task 2. It changes **only the reference**: the legs, the kind and the
    ledger key are what they were, because the README's posting table is the
    contract and a credit does not become a different posting for having
    gained a subject. What it does change is who can see it —
    :func:`refunded_for_order` reads the order's ``refunded_usd`` off this
    reference, and ``transactions.build`` maps it back to the reseller's own
    ``merchant_order_id``. Before it existed, the manual settlement support
    performs after a failed delivery moved the balance and appeared nowhere on
    the order it paid for.

    Passing ``None`` is the ordinary prepayment, unchanged in every observable
    way: ``Reference(type="merchant", id=merchant_id)``, the same row on
    ``/transactions`` with a null ``order_id``.

    **It has no default, and that is deliberate.** The defect M3b Task 2 came
    back to fix was a writer and a reader disagreeing about one word; the same
    field has a second axis, and a default would put the invisible behaviour
    on it. Omit the argument and money moves while the order it settles reads
    ``refunded_usd: "0.00"`` forever — mypy --strict happy, no test failing,
    and no way to re-point the transaction afterwards. Requiring the keyword
    turns that omission into a type error at every call site, including the
    ones a future milestone adds.

    **A settlement may not take an order past what it charged**
    (``order_already_settled``). ``refunded_usd`` is published as "how much of
    ``price_usd`` has been credited back", and this is what makes that
    sentence true rather than hopeful. It matters more since M3b Task 3 than
    it did before it: most failed deliveries now settle themselves within
    seconds, so an operator reaching for this form is the one more likely to
    be acting on what they saw a minute ago. The automatic refund refuses the
    mirror image of this — an order support already settled by hand — for the
    same reason and in the same words. Goodwill beyond the order's own price
    is still perfectly possible; it is an **unattributed** credit, which is
    what it always was.

    A fresh credit also enqueues ``balance.credited`` (spec §10), in this same
    transaction. A **replay** does not: it books nothing, and announcing money
    that did not move would have a reseller crediting their own end customer
    twice. The check is a read taken before the posting, because ``post()``
    gives its caller no way to tell a replay from a fresh write afterwards; two
    genuinely concurrent credits under one key can therefore both miss it and
    both announce, which is the at-least-once delivery a webhook receiver has
    to be built for regardless. The event's payload is deliberately untouched
    by ``order_id``: its key set is published as exactly
    ``{amount_usd, balance_usd}`` and a receiver is entitled to that.

    A replay does not re-point an existing transaction at another order, for
    the same reason it does not re-book another amount: ``post()`` replays by
    key **without comparing parameters**, so the returned transaction still
    carries the first call's reference. The admin response echoes it back for
    exactly that reason.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Who gets the money. Must exist; may be frozen.
        amount: Positive USD amount.
        actor: Who did it, e.g. ``admin:<id>`` — recorded on the transaction.
        idempotency_key: The caller's key; the replay handle.
        order_id: The order this credit settles, or ``None`` for an ordinary
            prepayment. Required as a keyword — see above. Must be an order
            **of this merchant's**.
        note: Optional free-text reason, kept in the transaction metadata.

    Returns:
        The ledger transaction (existing one on replay).

    Raises:
        ValidationError: If ``amount`` is not positive.
        NotFoundError: If no merchant with that id exists, or if ``order_id``
            is not an order of theirs (``order_not_found``).
        ConflictError: If ``order_id`` is given and this credit would take
            that order past what it charged (``order_already_settled``).
    """
    if amount <= 0:
        raise ValidationError("deposit credit must be positive", extra={"amount": str(amount)})
    await get_merchant(db, merchant_id)

    # Read *before* posting, because ``post()`` answers a replay with the
    # original transaction and gives the caller no way to tell the two apart
    # afterwards. A replay books nothing, so it must announce nothing: a
    # ``balance.credited`` for money that did not move would have a reseller
    # crediting their own customer twice. It is read here, before the
    # over-settlement guard, because that guard counts money this key may
    # already have moved — running it on a replay would answer ``409`` to the
    # operator's own retry and turn the endpoint's idempotency off.
    replayed = (
        await db.execute(
            select(WalletTransaction.id).where(WalletTransaction.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none() is not None

    if order_id is None:
        reference = wallet_service.Reference(type=MERCHANT_REFERENCE_TYPE, id=merchant_id)
    else:
        reference = await _resolve_order_reference(db, merchant_id=merchant_id, order_id=order_id)
        if not replayed:
            # ``reference.id``, not the caller's argument: the canonical
            # spelling is what ``refunded_for_order`` matches on, and
            # comparing a braced or undashed id against it would sum nothing
            # and wave every settlement through.
            await _refuse_over_settlement(
                db, merchant_id=merchant_id, order_id=reference.id, amount=amount
            )

    deposit = await deposit_account(db, merchant_id=merchant_id)
    received = await house_received_account(db)
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
        reference=reference,
        actor=actor,
        metadata={"note": note} if note is not None else {},
    )
    if not replayed:
        # In this transaction, with the credit, so a merchant is told about
        # money that is committed or about nothing at all.
        await webhooks.enqueue_balance_credited(
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

    deposit = await deposit_account(db, merchant_id=merchant_id)
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
    received = await house_received_account(db)
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
        idempotency_key=charge_key(order_id),
        reference=wallet_service.Reference(type=ORDER_REFERENCE_TYPE, id=order_id),
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

    Two things book a debit here. M3b's automatic refund will, when it lands;
    and since M3b Task 2 a support credit does, whenever the operator names
    the order it settles (``credit_deposit(order_id=…)``). Until that
    argument existed this function could only ever answer zero — the only
    surface that credited a deposit referenced the *merchant* while this read
    filters on the *order*, so the hand settlement support performs after a
    failed delivery was invisible on the very order it paid for. That is why
    both sides now spell the reference through
    :data:`ORDER_REFERENCE_TYPE`.

    It stays a read of a *direction* rather than of a transaction kind, so
    whatever M3b's automatic path calls its posting lands here with no change
    to this function and none to the published contract.

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
            WalletTransaction.reference_type == ORDER_REFERENCE_TYPE,
            WalletTransaction.reference_id == order_id,
        )
    )
    return Decimal((await db.execute(stmt)).scalar_one())


async def charged_for_order(db: AsyncSession, *, merchant_id: str, order_id: str) -> Decimal | None:
    """What this order actually took from the merchant's deposit, or ``None``.

    The mirror of :func:`refunded_for_order`, and the **only** authority on
    the amount an automatic refund may return. Read off the charge's own
    ledger transaction — found by its key, which is the tightest identity a
    posting has — rather than off ``order_items.unit_price_usd`` or the order
    total, because those answer a different question:

    - the line and the debit carry one number today and nothing enforces
      that they keep doing so. ``merchants.orders.place`` binds
      ``quote.price_for``'s result once and hands the same object to
      ``unit_price_usd_override`` and to this module's charge, so they agree
      by construction rather than by any constraint, test or trigger. A
      hand-edited, migrated or data-damaged line must not decide what we pay
      back — the ledger is where the money actually is;
    - an order that was never charged must refund **nothing**, and a price on
      a line is present whether or not any money followed it.

    ``None`` and ``Decimal("0")`` are different answers and only the first can
    occur: ``charge_deposit`` refuses a non-positive amount, so a charge
    transaction always moved something. ``None`` means *there is no charge* —
    impossible today (the debit and the order row are written in one
    transaction) and therefore a bug or a hand-edited row, which is why
    ``refund.refund_order`` refuses it out loud instead of treating it as
    "nothing to give back".

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The owning merchant — the account scope.
        order_id: The order whose charge to read.

    Returns:
        The amount charged, or ``None`` if this order has no charge posting.
    """
    normal = wallet_service.NORMAL_SIDE["merchant_deposit"]
    stmt = (
        select(func.sum(WalletPosting.amount))
        .join(WalletAccount, WalletAccount.id == WalletPosting.account_id)
        .join(WalletTransaction, WalletTransaction.id == WalletPosting.transaction_id)
        .where(
            WalletAccount.owner_type == "merchant",
            WalletAccount.owner_id == merchant_id,
            WalletAccount.kind == "merchant_deposit",
            WalletAccount.currency == DEPOSIT_CURRENCY,
            # The non-normal side of a debit-normal account: money leaving.
            WalletPosting.direction != normal,
            WalletTransaction.idempotency_key == charge_key(order_id),
        )
    )
    total = (await db.execute(stmt)).scalar_one_or_none()
    return None if total is None else Decimal(total)


async def _refuse_over_settlement(
    db: AsyncSession, *, merchant_id: str, order_id: str, amount: Decimal
) -> None:
    """Refuse a credit that would return more than the order ever charged.

    See :func:`credit_deposit` for why this exists. An order with no charge is
    left alone here — that is a broken row, and this guard is not the place
    that decides what to do about one; refusing on it would also make the
    hand settlement of a mis-booked order impossible.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The owning merchant — the account scope.
        order_id: The order, canonically spelled.
        amount: The credit being attempted.

    Raises:
        ConflictError: ``order_already_settled``.
    """
    charged = await charged_for_order(db, merchant_id=merchant_id, order_id=order_id)
    if charged is None:
        return
    already = await refunded_for_order(db, merchant_id=merchant_id, order_id=order_id)
    if already + amount > charged:
        raise ConflictError(
            "this order has already had its charge returned",
            code=CODE_ORDER_ALREADY_SETTLED,
            order_id=order_id,
            charged_usd=str(charged),
            returned_usd=str(already),
        )


__all__ = [
    "CHARGE_KEY_PREFIX",
    "CODE_ORDER_ALREADY_SETTLED",
    "CODE_ORDER_NOT_FOUND",
    "DEPOSIT_CURRENCY",
    "INSUFFICIENT_DEPOSIT_CODE",
    "MERCHANT_REFERENCE_TYPE",
    "ORDER_REFERENCE_TYPE",
    "charge_deposit",
    "charge_key",
    "charged_for_order",
    "credit_deposit",
    "deposit_account",
    "deposit_balance",
    "house_received_account",
    "list_deposit_transactions",
    "order_reference_of",
    "refunded_for_order",
]
