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

- the price is ``pricing.merchant_price`` over ``pricing.effective_cost`` and
  ``pricing.merchant_markup_pct``;
- the margin floor is ``pricing.violates_margin_floor`` against
  ``settings.merchant_margin_floor_pct`` — the *same* setting
  ``price_list.build`` reads, so the catalog and this path cannot disagree
  about which SKUs are sellable;
- the ±2% drift rule is ``pricing.price_to_charge``, its single home;
- the deposit legs are ``service.charge_deposit``, which follows the module
  README's posting table and is where the overdraw guard actually binds;
- buyability (active chain, brand maintenance, supplier stock) is
  ``orders.sku_is_buyable``, shared with retail checkout.

This module sequences them and turns each refusal into the documented RFC 7807
``code``.

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

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from yupay.core.config import get_settings
from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.core.logging import get_logger
from yupay.modules.catalog.models import Product, Sku
from yupay.modules.merchants import pricing, service
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

#: RFC 7807 ``code`` values this path can return (spec §9.4). Constants rather
#: than literals at the raise sites: they are a published contract, and a typo
#: in one is a silent break for every integrator switching on it.
CODE_ITEM_UNAVAILABLE: Final = "item_unavailable"
CODE_PRICE_CHANGED: Final = "price_changed"
CODE_MARGIN_FLOOR: Final = "margin_floor"
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


def _unavailable(sku_id: str, reason: str) -> NotFoundError:
    """A 404 a reseller can act on without opening a support ticket.

    Ruling 2: ``/catalog`` listing a SKU is not a promise that sourcing can
    fill it, and this is the only place a merchant finds out. So the body says
    *which* condition failed — a SKU pulled from B2B distribution, one whose
    cost is missing, and one the supplier is out of are three different
    problems with three different answers, and a bare "not found" makes them
    all look like a bad id.

    Args:
        sku_id: The SKU asked for. Our own identifier, never PII.
        reason: The discriminator — see the module README's table.

    Returns:
        The error to raise.
    """
    return NotFoundError(
        "this SKU cannot be ordered right now",
        code=CODE_ITEM_UNAVAILABLE,
        sku_id=sku_id,
        reason=reason,
    )


async def _load_orderable_sku(db: AsyncSession, *, sku_id: str) -> tuple[Sku, Decimal]:
    """Load a SKU and refuse it unless a merchant can buy it right now.

    Args:
        db: Session. The caller owns the transaction.
        sku_id: The SKU's id, already known to be a well-formed UUID (the
            schema parses it, so this never reaches Postgres as ``uuid = ''``
            — the ``DataError``-instead-of-a-clean-refusal trap
            ``merchant_id`` walked into in Task 2).

    Returns:
        The SKU with its product and brand loaded, and its wholesale cost.

    Raises:
        NotFoundError: ``item_unavailable``, with a ``reason``.
    """
    sku = (
        await db.execute(
            select(Sku)
            .options(selectinload(Sku.product).selectinload(Product.brand))
            .where(Sku.id == sku_id)
        )
    ).scalar_one_or_none()
    if sku is None:
        raise _unavailable(sku_id, "unknown_sku")
    product = sku.product
    brand = product.brand if product is not None else None
    if not sku.visible_b2b or brand is None or not brand.visible_b2b:
        raise _unavailable(sku_id, "not_b2b_visible")
    # The retail buyability rule, shared rather than restated: the active
    # chain, brand maintenance and supplier stock mean the same thing on both
    # surfaces, and a second copy of them would drift.
    if not orders.sku_is_buyable(sku):
        raise _unavailable(sku_id, "out_of_stock" if not sku.in_stock else "not_for_sale")
    if sku.variable_amount:
        # A customer-chosen amount has no wholesale price to quote: the B2B
        # formula is cost × markup, while these SKUs price off a guarded FX
        # rate and a margin multiplier. Not orderable in v1, and
        # ``expected_price`` would be meaningless for them.
        raise _unavailable(sku_id, "variable_amount")
    cost = pricing.effective_cost(sku)
    if cost is None:
        # Not sellable, never free — spec §8.2. The catalog withholds these
        # too, so reaching here means the SKU lost its cost between the poll
        # and the order.
        raise _unavailable(sku_id, "no_cost")
    return sku, cost


def _price_for(sku: Sku, cost: Decimal, merchant: Merchant, body: MerchantOrderCreateIn) -> Decimal:
    """Our price for this merchant, reconciled against the one they quoted.

    Args:
        sku: The SKU being bought.
        cost: Its wholesale cost — :func:`pricing.effective_cost`'s result,
            already known not to be ``None``.
        merchant: The buyer, whose ``markup_adjustment_pp`` (dormant in v1)
            makes this price theirs rather than anyone's.
        body: The request, for ``expected_price``.

    Returns:
        The price to charge.

    Raises:
        ValidationError: ``margin_floor`` when our own price fails the floor,
            or ``price_changed`` when the merchant's number has drifted too
            far from it.
    """
    current = pricing.merchant_price(cost, pricing.merchant_markup_pct(sku, merchant))
    floor_pct = get_settings().merchant_margin_floor_pct
    if pricing.violates_margin_floor(cost, current, floor_pct):
        # The same guard ``price_list.build`` applies, reading the same
        # setting, so a SKU the catalog withheld is a SKU this refuses.
        log.warning(
            "merchant_order_below_margin_floor",
            sku_code=sku.sku_code,
            floor_pct=str(floor_pct),
            hint="b2b_markup_pct is below settings.merchant_margin_floor_pct; "
            "fix the markup in the admin catalog",
        )
        raise ValidationError(
            "this SKU's price does not clear our minimum margin",
            code=CODE_MARGIN_FLOOR,
            sku_id=sku.id,
        )
    charge = pricing.price_to_charge(current, body.expected_price)
    if charge is None:
        raise ValidationError(
            "the price has moved since you read it",
            code=CODE_PRICE_CHANGED,
            sku_id=sku.id,
            current_price=str(current),
            expected_price=str(body.expected_price),
        )
    return charge


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
    return _out(order, balance=await service.deposit_balance(db, merchant_id=merchant_id))


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

    sku, cost = await _load_orderable_sku(db, sku_id=body.sku_id)
    price = _price_for(sku, cost, merchant, body)

    # The clean 409, before anything is written. Not the guarantee — that is
    # ``charge_deposit``'s row lock (Ruling 3) — but it is what keeps the
    # ordinary "you are out of money" answer from riding on a rolled-back
    # INSERT.
    balance = await service.deposit_balance(db, merchant_id=merchant.id)
    if balance < price:
        raise ConflictError(
            "deposit balance does not cover this order",
            code=service.INSUFFICIENT_DEPOSIT_CODE,
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
            currency=service.DEPOSIT_CURRENCY,
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

    await service.charge_deposit(db, merchant_id=merchant.id, amount=price, order_id=order.id)
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
    return _out(order, balance=await service.deposit_balance(db, merchant_id=merchant.id))


__all__ = [
    "CODE_ITEM_UNAVAILABLE",
    "CODE_MARGIN_FLOOR",
    "CODE_ORDER_ID_REUSED",
    "CODE_PRICE_CHANGED",
    "place",
]
