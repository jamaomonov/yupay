"""Reading one merchant order back — ``GET /merchant/v1/orders/{merchant_order_id}``.

The endpoint a reseller's back office lives on, and **the only place a
delivered voucher code is handed over**: spec §10's ``order.status_changed``
webhook (M3) deliberately will not carry it, because a webhook body is written
to the receiver's logs and to ours, and a voucher code is a bearer instrument —
whoever reads it can redeem it. A pull, over a signed request, scoped as
tightly as the order itself.

## Scope is the authenticated identity

The lookup is ``orders.find_merchant_order(merchant_id=…, merchant_order_id=…)``
— the same scoped read the order path uses for its replay check, so there is
one definition of "this merchant's order under this id". Nothing in the request
names a merchant: the path segment is the *reseller's own* id, and the merchant
half comes from the signature.

A merchant asking for someone else's order gets the same 404 as one asking for
an id that never existed. Not politeness — a distinguishable "not yours" is an
oracle: a reseller could walk a competitor's order numbering and learn their
volume from the status codes alone.

## The path segment is percent-decoded, and the signature is not

``merchant_order_id`` is ``^[\\x21-\\x7e]+$``, which **includes ``/``** (0x2F);
the auth README's own worked example is ``/merchant/v1/orders/my%2Forder``. So
the route is declared with Starlette's ``:path`` convertor and the decoded
segment is matched against the stored value — a plain ``{param}`` compiles to
``[^/]+`` and would 404 every order whose id contains a slash, which is a bug
that passes every test written with an id somebody made up.

What gets *signed* is the raw request line (``auth.request_target``), so
``%2F`` is signed as ``%2F``. The two facts have to stay apart: sign the bytes,
match the value.

## What is deliberately not here

- **Event payloads.** ``order.paid``'s payload holds the replay fingerprint of
  the reseller's request; ``order.failed``'s holds either an operator's
  free-text note or, when the automatic refund closed the order (M3c Task 6),
  an internal label. The timeline carries a kind and a timestamp, nothing else,
  so a reseller cannot tell the two apart here — ``failure_reason`` is what
  distinguishes them, and it is derived from the ledger.
- **A supplier's name, id or error.** The delivery artifact is filtered through
  ``fulfillment.buyer_safe_artifact`` — the same allow-list the storefront
  uses, shared rather than copied — and ``failure_reason`` is a closed
  vocabulary rather than an echo of ``task.last_error``.
- **Logging.** This path writes no log line at all. The code must not reach a
  log, a URL or an error body.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from yupay.core.errors import NotFoundError

# Both imported as submodules rather than through their facades: those facades
# re-export routers, so a facade import from here would pull the ``/api/v1``
# route stack into a module ``bootstrap`` imports while it is still building
# that very stack. The same reason ``orders.service`` reaches for
# ``affiliate.discount`` directly.
from yupay.modules.fulfillment import service as fulfillment
from yupay.modules.fulfillment import stall as fulfillment_stall
from yupay.modules.merchants import deposit, refund
from yupay.modules.merchants.machine_schemas import (
    MerchantDeliveryOut,
    MerchantOrderEventOut,
    MerchantOrderStatusOut,
)
from yupay.modules.orders import service as orders

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.merchants.models import Merchant
    from yupay.modules.orders.models import Order

#: RFC 7807 ``code`` for an id that is not this merchant's. Also the answer for
#: an id that belongs to somebody else — see the module docstring.
#:
#: Defined in ``deposit``, which answers the same word when a support credit
#: names an order that is not this merchant's (M3b Task 2). Two surfaces, one
#: published code, and no second literal to drift.
CODE_ORDER_NOT_FOUND: Final = deposit.CODE_ORDER_NOT_FOUND

#: Exactly ``MerchantOrderCreateIn.merchant_order_id``'s pattern and length.
#: Every stored id was written through that schema, so an id outside this
#: **cannot** exist — which is what lets a violation answer ``order_not_found``
#: rather than adding a 422 to the contract.
#:
#: It is a guard, not tidiness. The path segment arrives percent-decoded and
#: goes into a SQL comparison, so ``GET /merchant/v1/orders/%00null`` used to
#: reach Postgres as a string containing 0x00 and come back a **500**
#: (``invalid byte sequence for encoding "UTF8"``) — no leak, but a burnt
#: connection and a rollback per request, trivially scriptable by any
#: authenticated merchant. Everything else the reviewer threw at the route
#: (``..%2F..%2Fme``, ``a/b/c/d``, a 4000-character segment) already answered
#: 404; only NUL escaped, which is exactly the shape of a check that was
#: never written.
_STORABLE_ID: Final = re.compile(r"\A[\x21-\x7e]{1,128}\Z")

#: Timeline allow-list: the order-lifecycle events, mapped nowhere and emitted
#: verbatim. ``order_events`` is a general audit log and also holds internal
#: rows (``admin.deliveries_viewed`` records which operator read a customer's
#: codes), so this is an allow-list and a new kind is hidden until it is added
#: here **and** to the module README, which is what integrators read.
TIMELINE_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "order.created",
        "order.paid",
        "order.fulfilling",
        "order.delivered",
        "order.failed",
        "order.cancelled",
    }
)

#: ``failure_reason`` values. A closed vocabulary, additive only: a client
#: switches on these, and an operator's or a supplier's own words are internal.
REASON_ORDER_FAILED: Final = "order_failed"
REASON_FULFILLMENT_FAILED: Final = "fulfillment_failed"

#: A delivery that failed **and** whose money is already back on the deposit —
#: all of it.
#:
#: M3b Task 3 adds exactly **one** value here, not two, and this is it. The
#: distinction a reseller needs is "we are refunding you" versus "a human is
#: deciding", and the second half is what ``fulfillment_failed`` has always
#: meant — so the new word goes on the new fact and nothing a client switches
#: on today changes meaning. (Task 4 adds a second value to the *vocabulary*
#: — :data:`REASON_FULFILLMENT_DELAYED` — but not to this distinction: it is
#: about a delivery that has not finished, and every value here is about one
#: that has.)
#:
#: What is deliberately *not* in this vocabulary is whether the supplier kept
#: our money or we cannot tell. That is a fact about **our** supplier
#: relationship: a reseller who could read it off this field would learn which
#: of our suppliers is unreliable. It stays on the task, in the admin inbox
#: and in the ops alert, which is where the person who acts on it looks.
REASON_FULFILLMENT_REFUNDED: Final = "fulfillment_failed_refunded"

#: **The one value in this vocabulary that is not terminal.** The delivery has
#: stopped, the order has not: an operator is topping a supplier up and the
#: goods are still coming. *Keep polling* — do not re-order, do not refund
#: your end customer.
#:
#: M3b Task 4's single addition. Before it, a stall published ``None`` and was
#: byte-identical to an order placed thirty seconds ago, for ever — retail's
#: rule, right for a buyer with a support chat and useless to a machine with
#: an SLA and a polling loop that has no terminal condition.
#:
#: What it deliberately does not say is **why**. The cause is that *we* ran
#: out of balance at a named supplier, which is a fact about our supplier
#: funding rather than about this order; a reseller who could read it here
#: would learn which of our suppliers is short of money. Same reason ``SPENT``
#: and ``UNKNOWN`` are not distinguishable above.
#:
#: Because it is not terminal it changes how the whole field reads, and the
#: module README's contract text carries that: "any non-null value is
#: terminal" was true until this value existed and is now the one sentence an
#: integrator must not have copied.
REASON_FULFILLMENT_DELAYED: Final = "fulfillment_delayed"


def _failure_reason(
    order: Order, *, refunded: Decimal, charged: Decimal | None, stalled: bool
) -> str | None:
    """Why this order has stopped moving, or ``None`` if it has not.

    Four branches, in order, and **the first of them is the one M3c Task 6
    moved**.

    A **failed item whose money is all back** answers
    :data:`REASON_FULFILLMENT_REFUNDED` before anything else looks at
    ``order.status``. Until Task 6 the status branch came first and that was
    right, because a refund left ``order.status`` at ``fulfilling`` for ever,
    so ``failed`` could only mean "support closed this by hand". Task 6 makes a
    full automatic refund close the order — every way out of it is already
    refused by ``deposit_already_returned``, so "in progress" was a lie — and
    that puts ``status == "failed"`` on the *common* path. Leaving the old
    order would have collapsed every automatic refund to ``order_failed``,
    telling a reseller to contact support about money that is already on their
    deposit, in the same commit that added the terminal status.

    ``order.status == "failed"`` is therefore now "closed, and something is
    still owed": support closing a paid-but-undeliverable order by hand, or a
    part-settled one. The operator's reason is recorded on the timeline event
    and stays there — it is written for us, not for a reseller.

    Next the *item's* ``fulfillment_state`` alone. Reading the item rather than
    the fulfilment task is deliberate and inherits a rule ``fulfillment``
    already draws: when a supplier fails us for lack of **our own** balance the
    task goes ``failed`` but the item stays ``in_progress``, so the storefront
    keeps saying "processing" while an operator tops up and retries. Reporting
    that to a reseller as a *failure* would have them refund their end customer
    for an order we are about to deliver. Anything the storefront would show as
    an error, this shows too.

    Last ``stalled``, and it is the same state seen from the other side.
    Inheriting retail's rule was right about the word and wrong about the
    silence: a reseller has an SLA and a polling loop, so
    :data:`REASON_FULFILLMENT_DELAYED` says the order has stopped without
    saying it has failed. It comes last because both values above are
    *endings* and this one is not: an order support has closed by hand, and
    one whose delivery has terminally failed, are terminal whatever the task
    underneath them is still doing. The precedence is the contract — a client
    that read ``fulfillment_delayed`` off a closed order would go on waiting
    for it.

    Note the asymmetry with ``status``, and note where M3c Task 6 narrowed it:
    a supplier failure whose money did **not** come back leaves the order row in
    ``fulfilling`` — nothing advances it — so without this field it is
    indistinguishable from a busy one, forever. Same for a stall, which is why
    the delayed value exists. The one case that does advance the row is a
    **full** automatic refund, and that is a consequence of this function
    rather than an input to it: the closer asks the ledger, not this field.

    A failed delivery splits on ``refunded``, and it splits on the
    **ledger** rather than on anything the fulfilment path wrote down. That is
    what makes the field incapable of lying: it says "your money is back"
    only when money is actually back, so an automatic refund that raised, an
    order whose charge could not be found, and a supplier that kept our money
    all read ``fulfillment_failed`` — "a human is deciding" — without any of
    those paths having to remember to say so. The status the refund sets is not
    consulted for that: it is a *consequence* of the ledger reading square, and
    reading it back here would make the two able to disagree.

    **The comparison is against what the order was charged, not against
    zero**, because ``refunded`` is a sum and a sum is not a flag. A one-cent
    attributed credit on a $1.07 order is a partial settlement — a human
    mid-decision — and reading it as ``fulfillment_failed_refunded`` would
    tell the reseller what this module's own contract text says that value
    means: *"we have already put what you paid back … Refund your own
    customer. Nothing to chase."* They would refund $1.07 against $0.01
    received. It is also exactly the state that needs a person most, because
    ``refund.refund_order`` refuses to auto-refund into a partial decision, so
    that cent blocks the real refund for good.

    ``charged`` comes from the ledger too (``deposit.charged_for_order``), the
    same authority the refund reads its amount from — not from
    ``item.unit_price_usd``. The two hold one number today, by construction
    and not by any constraint (``merchants.orders.place`` passes one value to
    both), so reading the line would agree with the ledger right up until
    something edited it. ``None`` — an order with no charge posting at all —
    can never read as refunded: there is nothing it could be complete
    against.

    It counts money back **by any route**, which is why a hand settlement
    reaches it too: whether an operator or the saga returned the money is our
    business, not the reseller's, and ``refunded_usd`` beside it carries how
    much.

    ``order_failed`` still wins on a closure with money outstanding — none
    back, or only part of it. A closure is a human already in the loop with the
    reseller, and "contact support" is the right instruction while anything is
    owed. It stops winning only where there is nothing left to be in the loop
    about, which is exactly what ``settled_in_full`` measures.

    Args:
        order: The order, with its items loaded.
        refunded: What has come back to the deposit on this order — the same
            number the response's ``refunded_usd`` carries, passed in rather
            than re-read so the two cannot disagree.
        charged: What the order's deposit charge actually took, or ``None`` if
            it has no charge posting.
        stalled: Whether a fulfilment task of this order has stopped while the
            item it was fulfilling is still open —
            ``fulfillment.stall.order_is_stalled``, computed by the caller so
            this stays a pure function of facts and the transition table can
            be tested without a database.

    Returns:
        A value from the closed vocabulary above, or ``None``.
    """
    failed_item = any(item.fulfillment_state == "failed" for item in order.items)
    # ``refund.settled_in_full``, not a comparison spelled here: the
    # cancellation alert and the refund seam ask the same question, and two
    # spellings of one rule is how one of them starts saying "refunded" about
    # a cent.
    #
    # **Ahead of the status branch, and the order is the contract.** See the
    # docstring: since M3c Task 6 a full refund closes the order, so this shape
    # is what every automatic refund leaves behind. Swap these two and the
    # "your money is back" signal disappears from the path that produces it
    # most.
    if failed_item and refund.settled_in_full(charged=charged, returned=refunded):
        return REASON_FULFILLMENT_REFUNDED
    if order.status == "failed":
        return REASON_ORDER_FAILED
    if failed_item:
        return REASON_FULFILLMENT_FAILED
    return REASON_FULFILLMENT_DELAYED if stalled else None


async def failure_reasons(db: AsyncSession, *, orders: Sequence[Order]) -> dict[str, str | None]:
    """:func:`_failure_reason` for a page of orders, keyed by order id.

    **The second surface, not a second answer** (M3c Task 3). A terminal
    fulfilment failure deliberately leaves ``order.status`` alone — retail's
    rule, and it stays — so the admin list said «В работе» on a dead order for
    ever, while ``/merchant/v1`` had grown this exact field for this exact
    reason. The fix is the admin reading *this* function rather than spelling
    its own: two spellings of "why has this order stopped" is how the reseller's
    answer and the operator's answer start disagreeing about one order, and the
    operator is the one who then explains it to the reseller.

    It is batched because the caller is a **list** endpoint serving up to 500
    rows and a list endpoint may not ask per row (AGENTS.md §10). Three reads
    for a whole page, each already a batch of its own
    (``fulfillment.stall.stalled_order_ids``, ``deposit.charged_for_orders``,
    ``deposit.refunded_for_orders``), and the stall read skips a page with no
    open item on it.

    **Retail orders are included and get a real answer.** They have no deposit
    charge, so ``charged`` is ``None``, so ``settled_in_full`` is false and the
    refunded value can never be reached for one — the money branch is
    merchant-only by construction rather than by a gate. What retail does get
    is the other three, which is the point: the status lies for a storefront
    order in exactly the same way.

    Args:
        db: Session. The caller owns the transaction.
        orders: The page, with their items loaded.

    Returns:
        ``{order_id: reason}`` for **every** order given — the value is
        ``None`` for one that has not stopped, which is a different fact from
        an absent key and must not be conflated with one.
    """
    pairs = [(order.merchant_id, order.id) for order in orders if order.merchant_id is not None]
    stalled = await fulfillment_stall.stalled_order_ids(db, orders=orders)
    charged = await deposit.charged_for_orders(db, pairs=pairs)
    refunded = await deposit.refunded_for_orders(db, pairs=pairs)
    return {
        order.id: _failure_reason(
            order,
            refunded=refunded.get(order.id, Decimal("0")),
            charged=charged.get(order.id),
            stalled=order.id in stalled,
        )
        for order in orders
    }


async def _delivery(db: AsyncSession, order: Order) -> MerchantDeliveryOut | None:
    """The artifact this order handed over, filtered, or ``None``.

    One SKU per order means at most one delivery; the newest is taken if the
    invariant is ever widened, rather than assuming a count.

    Args:
        db: Session. The caller owns the transaction.
        order: The order.

    Returns:
        The delivery DTO, or ``None`` when nothing has been delivered.
    """
    rows = await fulfillment.list_deliveries_for_order(db, order_id=order.id)
    if not rows:
        return None
    row = rows[-1]
    return MerchantDeliveryOut(
        artifact_kind=row.artifact_kind,
        # The one place a voucher code leaves this system on purpose. The
        # allow-list is ``fulfillment``'s, shared with the storefront, so a
        # field a new supplier adds is hidden on both surfaces or neither.
        artifact=fulfillment.buyer_safe_artifact(row),
        delivered_at=row.delivered_at,
    )


async def read(
    db: AsyncSession, *, merchant: Merchant, merchant_order_id: str
) -> MerchantOrderStatusOut:
    """Read one of this merchant's orders back by their own id.

    Args:
        db: Session. The caller owns the transaction.
        merchant: The authenticated, non-frozen merchant. The **only** source
            of scope — nothing in the request names a merchant.
        merchant_order_id: The reseller's id for the order, already
            percent-decoded by the router. An id that does not exist, one that
            belongs to another merchant, and one that could never have been
            stored (:data:`_STORABLE_ID`) are all the same answer — the last of
            those never reaches the database at all.

    Returns:
        The order's status, timeline, delivered artifact and refund mark.

    Raises:
        NotFoundError: ``order_not_found``.
    """
    order = (
        await orders.find_merchant_order(
            db, merchant_id=merchant.id, merchant_order_id=merchant_order_id
        )
        if _STORABLE_ID.match(merchant_order_id) is not None
        else None
    )
    if order is None:
        raise NotFoundError("no order with that merchant_order_id", code=CODE_ORDER_NOT_FOUND)

    item = order.items[0]
    refunded = await deposit.refunded_for_order(db, merchant_id=merchant.id, order_id=order.id)
    charged = await deposit.charged_for_order(db, merchant_id=merchant.id, order_id=order.id)
    return MerchantOrderStatusOut(
        merchant_order_id=order.idempotency_key or "",
        order_id=order.id,
        status=order.status,
        sku_id=item.sku_id,
        price_usd=item.unit_price_usd,
        refunded_usd=refunded,
        created_at=order.created_at,
        paid_at=order.paid_at,
        delivered_at=order.delivered_at,
        failure_reason=_failure_reason(
            order,
            refunded=refunded,
            charged=charged,
            # One indexed read, and only while the order is still open — see
            # ``order_is_stalled``. A settled order asks the database nothing,
            # which matters on the endpoint we tell resellers to poll.
            stalled=await fulfillment_stall.order_is_stalled(db, order=order),
        ),
        delivery=await _delivery(db, order),
        # ``Order.events`` is eagerly loaded and already ordered
        # ``created_at, id`` by the relationship, so this is a filter and not
        # a query.
        timeline=[
            MerchantOrderEventOut(event=event.kind, at=event.created_at)
            for event in order.events
            if event.kind in TIMELINE_EVENTS
        ],
    )


__all__ = [
    "CODE_ORDER_NOT_FOUND",
    "REASON_FULFILLMENT_DELAYED",
    "REASON_FULFILLMENT_FAILED",
    "REASON_FULFILLMENT_REFUNDED",
    "REASON_ORDER_FAILED",
    "TIMELINE_EVENTS",
    "failure_reasons",
    "read",
]
