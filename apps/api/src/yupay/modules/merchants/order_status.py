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
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.merchants.models import Merchant
    from yupay.modules.orders.models import Order

#: RFC 7807 ``code`` for an id that is not this merchant's. Also the answer for
#: an id that belongs to somebody else — see the module docstring.
CODE_ORDER_NOT_FOUND: Final = "order_not_found"

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


def _failure_reason(order: Order) -> str | None:
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

    Args:
        order: The order, with its items loaded.

    Returns:
        A value from the closed vocabulary above, or ``None``.
    """
    if order.status == "failed":
        return REASON_ORDER_FAILED
    if any(item.fulfillment_state == "failed" for item in order.items):
        return REASON_FULFILLMENT_FAILED
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
            percent-decoded by the router. An id that does not exist and one
            that belongs to another merchant are the same answer.

    Returns:
        The order's status, timeline, delivered artifact and refund mark.

    Raises:
        NotFoundError: ``order_not_found``.
    """
    order = await orders.find_merchant_order(
        db, merchant_id=merchant.id, merchant_order_id=merchant_order_id
    )
    if order is None:
        raise NotFoundError("no order with that merchant_order_id", code=CODE_ORDER_NOT_FOUND)

    item = order.items[0]
    return MerchantOrderStatusOut(
        merchant_order_id=order.idempotency_key or "",
        order_id=order.id,
        status=order.status,
        sku_id=item.sku_id,
        price_usd=item.unit_price_usd,
        refunded_usd=await deposit.refunded_for_order(
            db, merchant_id=merchant.id, order_id=order.id
        ),
        created_at=order.created_at,
        paid_at=order.paid_at,
        delivered_at=order.delivered_at,
        failure_reason=_failure_reason(order),
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
    "REASON_ORDER_FAILED",
    "TIMELINE_EVENTS",
    "read",
]
