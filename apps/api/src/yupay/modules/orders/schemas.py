"""Pydantic DTOs for the ``orders`` HTTP surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer, field_validator

# Imported from ``schemas`` rather than the module's ``api`` on purpose: ``api``
# pulls in ``routes``, and a schema module reaching for a router is how import
# cycles start. ``ClientHints`` is a leaf value object either way.
from yupay.modules.catalog.unit_sku import UNIT_QTY_WIRE_MAX
from yupay.modules.evidence.schemas import ClientHints

OrderStatus = Literal[
    "pending_payment",
    "paid",
    "fulfilling",
    "fulfilled",
    "delivered",
    "failed",
    "cancelled",
    "expired",
    "refunded",
    "partially_refunded",
]


class OrderItemIn(BaseModel):
    """One line of a new-order request."""

    model_config = ConfigDict(extra="forbid")

    sku_id: str
    # The wire ceiling only lets a unit SKU (Telegram Stars) be bought in
    # bulk — it is not the real limit for anything else. The real limit is
    # enforced server-side per line, in
    # ``yupay.modules.orders.service._resolve_line_unit_price``, by
    # ``yupay.modules.catalog.unit_sku.assert_qty_allowed``.
    qty: int = Field(ge=1, le=UNIT_QTY_WIRE_MAX)
    fulfillment_data: dict[str, Any] = Field(default_factory=dict)
    # Set only for variable-amount SKUs (Steam wallet): how many dollars the
    # customer is buying. The price is derived from it server-side; the client
    # never sends a price.
    amount_usd: Decimal | None = Field(default=None, gt=0)


class OrderCreate(BaseModel):
    """Body of ``POST /api/v1/orders``."""

    model_config = ConfigDict(extra="forbid")

    currency: str = Field(min_length=3, max_length=8, default="USD")
    items: list[OrderItemIn] = Field(min_length=1, max_length=20)
    # Required for guest checkout; ignored when the caller is an authenticated
    # user, for whom it is also their identity on the order and cannot be
    # redirected. See ``delivery_email`` for where a signed-in buyer's mail goes.
    guest_email: EmailStr | None = None
    # Where to mail this order's confirmation and codes when the buyer is
    # signed in. Checkout has always shown a required email field to everyone
    # and dropped what signed-in customers typed into it, so they received
    # nothing. Ignored for guests: ``guest_email`` is both their address and
    # their claim on the order, and letting the two differ would mail the codes
    # somewhere the order does not belong.
    delivery_email: EmailStr | None = None
    # Passive browser signals kept for chargeback defence (ADR-0044). Optional
    # on purpose: a client that sends nothing still gets to buy, it just leaves
    # a thinner record behind.
    client_hints: ClientHints | None = None
    #: An affiliate partner's code, as typed. Validated server-side, and an
    #: unusable one is **ignored** rather than failing the order: the buyer
    #: already saw the verdict at preview time, and losing a sale over a
    #: discount that expired thirty seconds ago is the worse trade. The
    #: response's ``discount_charged`` says what actually happened.
    affiliate_code: str | None = Field(default=None, max_length=32)

    @field_validator("delivery_email", mode="before")
    @classmethod
    def _blank_is_absent(cls, value: object) -> object:
        """Read a blank string as "no address given", not as a malformed one.

        A client that has nothing to put here should omit the key, and ours now
        does. This exists for the ones that cannot: a browser holding a cached
        bundle keeps sending what it was built to send, so a fix that lives only
        in the new JavaScript leaves every already-loaded page failing until the
        cache turns over.

        And the failure it caused was the expensive kind. ``delivery_email`` is
        a convenience — where to mail codes the buyer can already read in the
        app — but an empty one failed ``EmailStr`` and took the **whole order**
        down with a 422 that reached the buyer as "order not created". 410 of
        606 accounts on prod have no address on file, because Telegram and Steam
        hand us none, so the field seeded blank and checkout refused the sale.
        Web checkout was failing about two orders in five.

        Same trade ``affiliate_code`` makes three lines up, for the same reason:
        losing a sale over an optional field is the worse outcome. A blank
        becomes ``None``; anything non-blank is still validated as an address,
        because a typo is a mistake worth reporting rather than discarding.

        **Only this field.** ``guest_email`` is a guest's identity and their
        claim on the order, not a convenience — blanking it would trade a clear
        "that is not an address" for a confusing "actor must be exactly one of",
        and there is no sale to save either way, because a guest without an
        address cannot be sent anything at all.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value


class OrderItemDisplay(BaseModel):
    """What the customer/admin should see for this line.

    Resolved from the SKU → product → brand chain at read time, so a renamed
    product reflects in old orders too. For an at-purchase-time snapshot we'd
    move this to a stored jsonb column — deferred until we hit the use case.
    """

    model_config = ConfigDict(extra="forbid")

    brand_slug: str
    brand_name: str
    product_slug: str
    product_name: str
    product_kind: str  # "top_up" | "voucher"
    sku_code: str
    denomination: str | None
    region: str | None
    image_url: str | None
    # A variable-amount SKU's ``denomination`` is a generic label ("Любая
    # сумма"), not the amount the customer actually bought — the client needs
    # this flag to know when ``OrderItemOut.unit_price_usd`` (which for a
    # variable line *is* the chosen dollar amount, see
    # ``_resolve_line_unit_price``) is worth surfacing as "credited".
    variable_amount: bool


#: ``fulfillment_data`` keys a customer must never see in their own order
#: response, even though the persisted row and fulfilment both need them.
#: Currently just the Steam gift checkout hook's wholesale cost (see
#: ``gifts.checkout.price_gift_line``) — left in place, a buyer could back
#: out our exact margin as ``unit_price_usd - supplier_price_usd``. Mirrors
#: how ``OrderItem.cost_usdt`` (orders/models.py) is kept off this schema's
#: field list entirely; this key can't be kept off the *list* the same way
#: because it lives inside a free-form JSONB column, so it's redacted at
#: serialization time instead.
_CUSTOMER_HIDDEN_FULFILLMENT_KEYS = frozenset({"supplier_price_usd"})


class OrderItemOut(BaseModel):
    """One line of an order response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    sku_id: str
    qty: int
    unit_price_usd: Decimal
    fulfillment_state: str
    fulfillment_data: dict[str, Any]
    display: OrderItemDisplay | None = None

    @field_serializer("fulfillment_data")
    def _serialize_fulfillment_data(self, value: dict[str, Any]) -> dict[str, Any]:
        """Drop supplier-cost keys before this line reaches a customer.

        ``OrderItemAdminOut`` redefines this same method to pass the dict
        through unredacted — an operator needs the real cost to see the
        actual margin on a line.
        """
        if not _CUSTOMER_HIDDEN_FULFILLMENT_KEYS.intersection(value):
            return value
        return {k: v for k, v in value.items() if k not in _CUSTOMER_HIDDEN_FULFILLMENT_KEYS}


class OrderItemAdminOut(OrderItemOut):
    """Admin view of an order line — adds the internal supplier order id.

    Overrides :meth:`OrderItemOut._serialize_fulfillment_data` with a plain
    passthrough: unlike the customer-facing response, the admin view is
    allowed to show ``supplier_price_usd`` and any other cost data.
    """

    supplier_order_id: str | None = None

    @field_serializer("fulfillment_data")
    def _serialize_fulfillment_data(self, value: dict[str, Any]) -> dict[str, Any]:
        return value


class OrderEventOut(BaseModel):
    """One audit row."""

    model_config = ConfigDict(from_attributes=True)

    kind: str
    payload: dict[str, Any]
    actor: str | None
    created_at: datetime


class OrderOut(BaseModel):
    """Full order response (matches list and detail)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: OrderStatus
    currency: str
    total_usd: Decimal
    total_charged: Decimal
    #: What an affiliate discount took off, in ``currency``. Zero when none —
    #: which is how the client tells that a code it sent was not applied.
    discount_charged: Decimal = Decimal("0")
    fx_snapshot_id: str | None
    expires_at: datetime
    created_at: datetime
    paid_at: datetime | None
    fulfilled_at: datetime | None
    delivered_at: datetime | None
    cancelled_at: datetime | None
    items: list[OrderItemOut]
    payment_provider: str | None = None
    #: ``catalog`` (storefront sale) or ``wallet_topup`` (1:1 balance deposit).
    purpose: str = "catalog"


class OrderListOut(BaseModel):
    """Response for list endpoints."""

    items: list[OrderOut]


class OrderAdminOut(OrderOut):
    """Same as :class:`OrderOut` but exposes actor identifiers + audit trail."""

    items: list[OrderItemAdminOut]  # type: ignore[assignment]
    #: What the order is actually worth in USD, markup included — see
    #: ``orders.revenue``. Distinct from ``total_usd``, which on a
    #: variable-amount line is the face value the customer chose (the $10 of
    #: Steam credit), not the ~$11.30 they paid for it. Admin-only: an operator
    #: comparing orders across currencies needs the real figure, and the
    #: customer has no use for our markup. ``None`` only when a line's SKU
    #: could not be loaded.
    charged_usd: Decimal | None = None
    user_id: str | None
    # Plain ``str`` (not ``EmailStr``) on purpose: this is a read-only view of an
    # already-stored address, and re-validating it on output makes the whole
    # admin list 500 on a single odd row. Addresses that are legal to store but
    # rejected by strict RFC email validation — e.g. reserved-TLD test addresses
    # like ``uzum-test@test.local`` seeded during sandbox payment testing — must
    # still render. Email format is enforced at write time (``OrderCreate``).
    guest_email: str | None
    #: The reseller that placed this order through ``/merchant/v1``, or
    #: ``None`` for a retail one. The **third** arm of
    #: ``ck_orders_actor_exclusive``, and the one the admin surface did not
    #: have until M3c Task 2: a merchant order arrived with both retail arms
    #: null and was rendered «Гость» — the one class of order whose owner is
    #: never in doubt, shown as the one class whose owner is anonymous.
    merchant_id: str | None = None
    #: That reseller's title, resolved at read time. Carried **beside** the id
    #: rather than instead of it because they answer different questions: an
    #: operator recognises "Reseller LLC", and the id is what they paste into
    #: a ledger query. ``None`` on a retail order, and — in principle — on a
    #: merchant order whose row vanished, which ``ondelete="RESTRICT"`` on
    #: ``orders.merchant_id`` makes impossible.
    merchant_title: str | None = None
    #: Which surface the order came from — ``web`` / ``miniapp`` / ``bot``
    #: (client-declared), ``merchant_api`` (set server-side for a B2B order),
    #: or ``unknown``. ``merchant_panel`` joins the set when M4's cabinet
    #: ships. Admin-only: it is operator context, and a customer has no use
    #: for being told which of our own apps they used.
    source: str = "unknown"
    #: Why this order has stopped moving, or ``None`` if it has not — the same
    #: closed vocabulary ``/merchant/v1`` publishes (``order_failed`` /
    #: ``fulfillment_failed`` / ``fulfillment_failed_refunded`` /
    #: ``fulfillment_delayed``), computed by the same function
    #: (``merchants.order_status.order_stop_states``).
    #:
    #: It sits **beside** ``status`` and never replaces it, because the two
    #: answer different questions: a terminal fulfilment failure deliberately
    #: leaves ``status`` at ``fulfilling`` — an operator may still top a
    #: supplier up, retry, or deliver by hand — so the list said «В работе» on
    #: a dead order for ever. Retail orders get a real value too: the status
    #: lies for a storefront order in exactly the same way, and only the
    #: refunded value is merchant-shaped (it is measured off the deposit
    #: ledger, which a retail order has no rows in).
    failure_reason: str | None = None
    #: What this order took from the merchant's USD deposit, off the ledger —
    #: ``None`` for every retail order (there is no deposit) and for a merchant
    #: order with no charge posting, which is a bug rather than a state. A
    #: merchant order has no ``Payment`` row at all, so before M3c Task 4 the
    #: operator's page said «Платежи (0)» and nothing else about the money.
    deposit_charged_usd: Decimal | None = None
    #: What has come back on it, by any route — the drain's automatic refund
    #: and any settlement support booked against the order. ``0`` when nothing
    #: has, and never more than ``deposit_charged_usd``: the cap is enforced at
    #: the posting (``order_already_settled``).
    deposit_returned_usd: Decimal = Decimal("0")
    events: list[OrderEventOut]


class OrderFailIn(BaseModel):
    """Body for the admin "close this order as failed" action."""

    model_config = ConfigDict(extra="forbid")

    # Required and non-blank: the reason lands on the order timeline and is the
    # only record of why a paid order was closed without delivery.
    reason: str = Field(..., min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 3:
            raise ValueError("reason must be at least 3 non-blank characters")
        return cleaned


class OrderAdminListOut(BaseModel):
    items: list[OrderAdminOut]
    total: int = 0


class ClaimOut(BaseModel):
    """Response of ``POST /orders/claim`` — how many guest orders were migrated."""

    claimed: int


__all__ = [
    "ClaimOut",
    "OrderAdminListOut",
    "OrderAdminOut",
    "OrderCreate",
    "OrderEventOut",
    "OrderItemAdminOut",
    "OrderItemDisplay",
    "OrderItemIn",
    "OrderItemOut",
    "OrderListOut",
    "OrderOut",
    "OrderStatus",
]
