"""Placing a merchant order against the prepaid deposit — the money path.

``POST /merchant/v1/orders`` (spec §8.4, §9.3, §9.5). One SKU per order, one
transaction, and no second definition of what an order is: the row is built by
``orders.create_order`` exactly like a storefront sale, with a **price
override** carrying the wholesale price this module computed. The alternative
— a forked ``create_order`` for B2B — is how the two surfaces start disagreeing
about qty rules, ``fulfillment_data`` validation or which statuses exist, and
the disagreement is only ever found in production.

## Where each rule lives

Nothing about money is decided in this file:

- **what may be bought and at what price** — the SKU's orderability, the
  margin floor and the ±2 % drift rule — is ``quote.py``, which owns every
  refusal a merchant can meet before their deposit is touched;
- the deposit legs are ``deposit.charge_deposit``, which follows the module
  README's posting table and is where the overdraw guard actually binds.

This module sequences them: replay, quote, debit, order row, fulfilment.

## Idempotency

Keyed on the merchant's own ``merchant_order_id``, **never** on an
``Idempotency-Key`` header (spec §9.3). That is not a convenience: a signature
on this API is deliberately not single-use — a replaying attacker and a
retrying client are byte-identical, so a server-side marker cannot separate
them — which makes endpoint idempotency the only thing that keeps a replayed
mutation harmless. The race resolves in ``uq_orders_idem_merchant``, and every
side effect is idempotent too: ``charge_deposit``'s ledger key is derived from
the order id, so no path spends the deposit twice.

## Transaction shape

The route's session is one transaction, committed by the dependency. Order
INSERT → deposit debit → ``paid`` → fulfilment *enqueue* all ride it, so a
failure anywhere leaves neither an order nor a debit. The one deliberate
exception is the insufficient-deposit *pre*-check, which runs before any row is
written so the common case answers ``409`` without an aborted INSERT behind it.

**Fulfilment is enqueued, never executed inline** — this path forces
``fulfilment_async`` on regardless of the deployment's setting, because a
supplier purchase inside the money transaction can leave the supplier paid and
no record of it. :func:`_enqueue_only` carries the argument. The practical
consequence: **the merchant channel depends on the worker being up.** A stalled
worker shows as orders sitting in ``fulfilling`` with the deposit correctly
debited — visible, and recoverable.

## PII

``fulfillment_data`` carries the reseller's end-customer identifiers (player
ids, logins). They are transit-only: persisted on the order line because
fulfilment needs them, never logged, and never in a URL.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING, Final

from yupay.core.config import get_settings
from yupay.core.errors import ConflictError
from yupay.core.logging import get_logger
from yupay.modules.merchants import deposit, quote
from yupay.modules.merchants.machine_schemas import MerchantOrderCreateIn, MerchantOrderOut

# Imported as a submodule rather than through the ``orders`` facade: that
# facade re-exports a router, so a facade import from here would pull the
# ``/api/v1`` route stack into a module ``bootstrap`` imports while it is still
# building that very stack. The same reason ``orders.service`` reaches for
# ``affiliate.discount`` directly, and ``payments.service`` for
# ``fulfillment.service``.
from yupay.modules.orders import service as orders

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.core.config import Settings
    from yupay.modules.merchants.models import Merchant
    from yupay.modules.orders.models import Order

log = get_logger("yupay.merchants.orders")

_CENT: Final = Decimal("0.01")

#: Not in spec §9.4's list, which names only the business refusals. §9.3
#: specifies the behaviour — same id, different body ⇒ 409 — without naming a
#: code; this is it.
CODE_ORDER_ID_REUSED: Final = "order_id_reused"

#: Where the replay fingerprint is recorded and read back: the ``order.paid``
#: event ``orders.mark_merchant_order_paid`` writes. See its docstring for why
#: that event and not a column.
PAID_EVENT: Final = "order.paid"


def _request_digest(body: MerchantOrderCreateIn) -> str:
    """Fingerprint the parts of a request that make it *this* order.

    Compared on replay to tell a retry (same intent) from a reused
    ``merchant_order_id`` (a client bug, and a ``409``). ``expected_price`` is
    quantized first so ``"1.0"`` and ``"1.00"`` — the same number, two
    spellings, both accepted by the schema — do not read as two intents.

    A digest, not the body: it only has to decide equality, and the values
    inside it are the reseller's end-customer identifiers.

    Args:
        body: The parsed request.

    Returns:
        Lowercase hex SHA-256 of the canonical form.
    """
    canonical = json.dumps(
        {
            "sku_id": body.sku_id,
            "expected_price": str(body.expected_price.quantize(_CENT)),
            "fulfillment_data": body.fulfillment_data,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _recorded_digest(order: Order) -> str | None:
    """The fingerprint recorded when this order was placed, if any."""
    for event in order.events:
        if event.kind == PAID_EVENT:
            recorded = event.payload.get("request_digest")
            return recorded if isinstance(recorded, str) else None
    return None


def _out(order: Order, *, balance: Decimal) -> MerchantOrderOut:
    """Project a persisted merchant order onto the wire contract."""
    item = order.items[0]
    return MerchantOrderOut(
        merchant_order_id=order.idempotency_key or "",
        order_id=order.id,
        status=order.status,
        sku_id=item.sku_id,
        price_usd=item.unit_price_usd,
        balance_usd=balance,
        created_at=order.created_at,
    )


async def _replayed(
    db: AsyncSession, order: Order, *, merchant_id: str, digest: str
) -> MerchantOrderOut:
    """Return an order already placed under this ``merchant_order_id``.

    Args:
        db: Session. The caller owns the transaction.
        order: The existing order.
        merchant_id: Whose order it is — the balance to report.
        digest: The fingerprint of the request now asking for it.

    Returns:
        The existing order, unchanged and not debited a second time.

    Raises:
        ConflictError: The id was reused for a materially different request
            (spec §9.3).
    """
    if _recorded_digest(order) != digest:
        raise ConflictError(
            "this merchant_order_id already belongs to a different order",
            code=CODE_ORDER_ID_REUSED,
            merchant_order_id=order.idempotency_key,
            order_id=order.id,
        )
    return _out(order, balance=await deposit.deposit_balance(db, merchant_id=merchant_id))


def _enqueue_only() -> Settings:
    """Settings for :func:`fulfillment.start_for_order` with the queue forced on.

    ``fulfilment_async`` is off by default and off on production, and with it
    off ``start_for_order`` runs the **supplier purchase inline, inside this
    transaction**. That is a shape a money path cannot have: ``process_task``
    catches ``FulfillerError`` and ``FulfillerNotIntegratedError`` and nothing
    else, so anything raising after the supplier is paid but before the commit
    — an unwrapped client error on a later call, a flush, ``_try_settle_order``
    — rolls back the order, the debit, the task and the delivery while the
    supplier keeps the money. The merchant then does exactly what our contract
    tells them to do, retries the same ``merchant_order_id``, finds nothing,
    and buys it a second time. AGENTS.md §10 forbids synchronous external HTTP
    in a request handler for this reason.

    So the queue is forced here rather than left to an env var. The two
    failure modes are not comparable: a stalled worker leaves an order visibly
    ``fulfilling`` with the money correctly debited and every row present and
    recoverable, while an inline failure leaves a paid supplier and no record
    at all. And enqueue-only is contract-compatible **today** — the machine API
    already returns ``status: "fulfilling"`` and already tells resellers to
    poll, so nothing about the wire changes.

    ``fulfilment_async`` is read in exactly one place
    (``fulfillment.service.start_for_order``, from ``settings or
    get_settings()``), so this override cannot be undone further down: with it
    on, every task is left ``pending`` and ``_try_settle_order`` returns early
    because none is ``succeeded``.

    Returns:
        A copy of the live settings with ``fulfilment_async`` on. Everything
        else is whatever the process is configured with — this overrides one
        flag, it does not build a settings object of its own.
    """
    return get_settings().model_copy(update={"fulfilment_async": True})


async def place(
    db: AsyncSession, *, merchant: Merchant, body: MerchantOrderCreateIn
) -> MerchantOrderOut:
    """Place one merchant order and settle it from the deposit.

    See the module docstring for the flow and where each rule lives. The order
    is born ``paid`` and fulfilment starts inside the same transaction, so by
    the time this returns the status is whatever fulfilment left it at —
    ``fulfilling`` for anything with a task still to run.

    Args:
        db: Session. The caller owns the transaction.
        merchant: The authenticated, non-frozen merchant.
        body: The parsed request.

    Returns:
        The order, plus the deposit balance left after it.

    Raises:
        NotFoundError: ``item_unavailable``.
        ValidationError: ``margin_floor``, ``price_changed``, or a
            ``fulfillment_data`` payload the product's schema rejects.
        ConflictError: ``insufficient_deposit`` or ``order_id_reused``.
    """
    # Imported here, not at module scope: ``orders.schemas`` is a leaf, but
    # keeping every ``orders`` import in one place above would mean importing
    # the facade, and importing two different halves of one module reads worse
    # than one local import that says why it is local.
    from yupay.modules.orders.schemas import OrderCreate, OrderItemIn

    digest = _request_digest(body)
    already = await orders.find_merchant_order(
        db, merchant_id=merchant.id, merchant_order_id=body.merchant_order_id
    )
    if already is not None:
        return await _replayed(db, already, merchant_id=merchant.id, digest=digest)

    sku, cost = await quote.load_orderable_sku(db, sku_id=body.sku_id)
    price = quote.price_for(sku, cost, merchant, body)

    # The clean 409, before anything is written. Not the guarantee — that is
    # ``charge_deposit``'s row lock (Ruling 3) — but it is what keeps the
    # ordinary "you are out of money" answer from riding on a rolled-back
    # INSERT.
    balance = await deposit.deposit_balance(db, merchant_id=merchant.id)
    if balance < price:
        raise ConflictError(
            "deposit balance does not cover this order",
            code=deposit.INSUFFICIENT_DEPOSIT_CODE,
            # ROUND_DOWN, matching ``charge_deposit`` and
            # ``machine_schemas.UsdBalance``: three roundings of one quantity
            # must agree, and the direction is a policy, not formatting —
            # never advertise more than the merchant holds. Today every
            # balance is already a whole cent, so this is a no-op; M3's
            # refunds are where it stops being one.
            balance_usd=str(balance.quantize(_CENT, rounding=ROUND_DOWN)),
            required_usd=str(price),
        )

    actor = orders.Actor(user_id=None, email=None, merchant_id=merchant.id)
    order = await orders.create_order(
        db,
        OrderCreate(
            currency=deposit.DEPOSIT_CURRENCY,
            items=[OrderItemIn(sku_id=sku.id, qty=1, fulfillment_data=body.fulfillment_data)],
        ),
        actor=actor,
        idempotency_key=body.merchant_order_id,
        unit_price_usd_override=(price,),
    )
    if order.status != "pending_payment":
        # A concurrent request with the same key won the unique index while we
        # were building ours; ``create_order`` rolled back and handed us the
        # winner's row, already paid and already debited. Postgres blocks the
        # loser's INSERT until the winner's transaction ends, so what we read
        # here is committed, not half-written.
        return await _replayed(db, order, merchant_id=merchant.id, digest=digest)

    await deposit.charge_deposit(db, merchant_id=merchant.id, amount=price, order_id=order.id)
    await orders.mark_merchant_order_paid(db, order=order, actor=actor, request_digest=digest)

    # The same call the payment path makes, with two deliberate differences.
    #
    # No risk gate: ``orders.risk`` exists so a card charge is not delivered
    # before a human can look at it, and a merchant order has no card and no
    # chargeback — the money is ours already, transferred and credited by
    # support days earlier. Holding it would break the contract's promise
    # (born paid, fulfilment started) for a risk this channel cannot carry.
    #
    # And **always asynchronous**, whatever ``fulfilment_async`` says. See
    # :func:`_enqueue_only` for why that is a call-site decision and not an
    # operator's.
    from yupay.modules.fulfillment import service as fulfillment

    await fulfillment.start_for_order(db, order_id=order.id, settings=_enqueue_only())

    log.info(
        "merchant_order_placed",
        merchant_id=merchant.id,
        order_id=order.id,
        sku_code=sku.sku_code,
        price_usd=str(price),
    )
    return _out(order, balance=await deposit.deposit_balance(db, merchant_id=merchant.id))


__all__ = [
    "CODE_ORDER_ID_REUSED",
    "PAID_EVENT",
    "place",
]
