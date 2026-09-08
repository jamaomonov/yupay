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
  the reseller's request; ``order.failed``'s holds an operator's free-text
  note. The timeline carries a kind and a timestamp, nothing else.
- **A supplier's name, id or error.** The delivery artifact is filtered through
  ``fulfillment.buyer_safe_artifact`` — the same allow-list the storefront
  uses, shared rather than copied — and ``failure_reason`` is a closed
  vocabulary rather than an echo of ``task.last_error``.
- **Logging.** This path writes no log line at all. The code must not reach a
  log, a URL or an error body.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from yupay.core.errors import NotFoundError

# Both imported as submodules rather than through their facades: those facades
# re-export routers, so a facade import from here would pull the ``/api/v1``
# route stack into a module ``bootstrap`` imports while it is still building
# that very stack. The same reason ``orders.service`` reaches for
# ``affiliate.discount`` directly.
from yupay.modules.fulfillment import service as fulfillment
from yupay.modules.merchants import deposit
from yupay.modules.merchants.machine_schemas import (
    MerchantDeliveryOut,
    MerchantOrderEventOut,
    MerchantOrderStatusOut,
)
from yupay.modules.orders import service as orders

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from decimal import Decimal

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

#: A delivery that failed **and** whose money is already back on the deposit.
#:
#: M3b Task 3 adds exactly **one** value here, not two, and this is it. The
#: distinction a reseller needs is "we are refunding you" versus "a human is
#: deciding", and the second half is what ``fulfillment_failed`` has always
#: meant — so the new word goes on the new fact and nothing a client switches
#: on today changes meaning.
#:
#: What is deliberately *not* in this vocabulary is whether the supplier kept
#: our money or we cannot tell. That is a fact about **our** supplier
#: relationship: a reseller who could read it off this field would learn which
#: of our suppliers is unreliable. It stays on the task, in the admin inbox
#: and in the ops alert, which is where the person who acts on it looks.
REASON_FULFILLMENT_REFUNDED: Final = "fulfillment_failed_refunded"


def _failure_reason(order: Order, *, refunded: Decimal) -> str | None:
    """Why this order has stopped moving, or ``None`` if it has not.

    Two sources, in order:

    ``order.status == "failed"`` is support closing a paid-but-undeliverable
    order by hand. The operator's reason is recorded on the timeline event and
    stays there — it is written for us, not for a reseller.

    Otherwise the *item's* ``fulfillment_state``. Reading the item rather than
    the fulfilment task is deliberate and inherits a rule ``fulfillment``
    already draws: when a supplier fails us for lack of **our own** balance the
    task goes ``failed`` but the item stays ``in_progress``, so the storefront
    keeps saying "processing" while an operator tops up and retries. Reporting
    that to a reseller as a failure would have them refund their end customer
    for an order we are about to deliver. Anything the storefront would show as
    an error, this shows too.

    Note the asymmetry with ``status``: a supplier failure leaves the order row
    in ``fulfilling`` — nothing advances it — so without this field a stalled
    order is indistinguishable from a busy one, forever.

    A failed delivery then splits on ``refunded``, and it splits on the
    **ledger** rather than on anything the fulfilment path wrote down. That is
    what makes the field incapable of lying: it says "your money is back"
    only when money is actually back, so an automatic refund that raised, an
    order whose charge could not be found, and a supplier that kept our money
    all read ``fulfillment_failed`` — "a human is deciding" — without any of
    those paths having to remember to say so.

    It counts money back **by any route**, which is why a hand settlement
    reaches it too: whether an operator or the saga returned the money is our
    business, not the reseller's, and ``refunded_usd`` beside it carries how
    much.

    ``order_failed`` still wins when support closed the order by hand. A
    closure is a human already in the loop with the reseller, and the amount
    is on ``refunded_usd`` either way; layering a fourth combination onto a
    field a client switches on would buy nothing.

    Args:
        order: The order, with its items loaded.
        refunded: What has come back to the deposit on this order — the same
            number the response's ``refunded_usd`` carries, passed in rather
            than re-read so the two cannot disagree.

    Returns:
        A value from the closed vocabulary above, or ``None``.
    """
    if order.status == "failed":
        return REASON_ORDER_FAILED
    if any(item.fulfillment_state == "failed" for item in order.items):
        return REASON_FULFILLMENT_REFUNDED if refunded > 0 else REASON_FULFILLMENT_FAILED
    return None


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
        failure_reason=_failure_reason(order, refunded=refunded),
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
    "REASON_FULFILLMENT_FAILED",
    "REASON_FULFILLMENT_REFUNDED",
    "REASON_ORDER_FAILED",
    "TIMELINE_EVENTS",
    "read",
]
