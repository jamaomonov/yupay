"""SQLAlchemy ORM for the ``orders`` module. See ADR-0011 for the FSM and snapshots."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yupay.core.db import Base

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from yupay.modules.catalog.models import Sku
    from yupay.modules.payments.models import Payment


class Order(Base):
    """Order aggregate. Customer-facing total, status, frozen FX snapshot."""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    guest_email: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    #: The third actor arm (B2B): set when a reseller placed this order via
    #: ``/merchant/v1``. RESTRICT, not SET NULL like ``user_id`` — merchant
    #: orders are financial history, so a merchant that has traded gets
    #: ``status='frozen'``, never deleted.
    merchant_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("merchants.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    total_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    total_charged: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    #: The affiliate code applied at checkout, if any. Kept for the receipt and
    #: the order history; the money effect is already inside ``total_charged``.
    affiliate_code_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("affiliate_codes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    #: What the affiliate discount took off, in this order's currency.
    #: NOT NULL DEFAULT 0 rather than nullable — every order without a code
    #: genuinely had a zero discount, and a zero is easier to sum than a NULL.
    discount_charged: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, server_default=text("0"), default=Decimal("0")
    )
    fx_snapshot_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("fx_snapshots.id", ondelete="RESTRICT"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Which surface placed the order. An operator's "where did this come from",
    # never an authorisation input — nothing is gated on it, on any row.
    #
    # `unknown` covers anything that did not say, including every order placed
    # before this column existed.
    #
    # Two provenances, not one, and a reader must not assume the first
    # describes every row:
    #   * retail (`web` / `miniapp` / `bot`) is **client-declared** — the
    #     `X-Yupay-Surface` header the frontends send, normalised against
    #     `service.ORDER_SOURCES` so an unrecognised value records as
    #     `unknown` rather than being trusted verbatim;
    #   * B2B (`merchant_api`, and `merchant_panel` once M4's cabinet ships) is
    #     set **server-side**, on a path that has already authenticated which
    #     merchant is calling. Neither is in `ORDER_SOURCES`, so no client can
    #     declare itself one. That makes the field stronger on those rows, not
    #     weaker — but still not an authorisation input.
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'unknown'")
    )
    # ``catalog`` is a storefront sale; ``wallet_topup`` is a 1:1 balance
    # deposit with no SKUs (ADR-0058). Default keeps every pre-column row a
    # normal order.
    purpose: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'catalog'"), default="catalog"
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Where to send this order's codes when the buyer is signed in. ``guest_email``
    # cannot hold it — it is half of ``ck_orders_actor_exclusive`` and stays NULL
    # on a signed-in order — which is why a signed-in customer typed an address
    # into a required checkout field and received nothing.
    delivery_email: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    ua_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        # `created_at` alone is a tie: it defaults to CURRENT_TIMESTAMP, which
        # in Postgres is the *transaction* start, so every row a checkout
        # writes shares one value. The id breaks it — `new_id()` is UUIDv7, so
        # id order is insertion order.
        order_by="OrderItem.created_at, OrderItem.id",
    )
    events: Mapped[list[OrderEvent]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        # Same tie as the items above, and here it was visible: settlement
        # writes paid/fulfilling/delivered in one transaction, so the admin
        # timeline showed "Доставлен" above "Выдаётся" above "Оплачен".
        order_by="OrderEvent.created_at, OrderEvent.id",
    )
    # One-directional (no back_populates) so this module doesn't force an
    # import of yupay.modules.payments.models at class-definition time —
    # viewonly because orders never mutate payments; lazy="raise" guards
    # against an accidental N+1 (a read path that forgot the selectinload
    # in _order_load_options will error loudly in tests, not silently fan out).
    payments: Mapped[list[Payment]] = relationship(
        "Payment",
        primaryjoin="Order.id == foreign(Payment.order_id)",
        viewonly=True,
        lazy="raise",
    )

    __table_args__ = (
        # Exactly one actor arm: user, guest, or merchant. Bare suffix, not the
        # full name — the metadata's naming convention (``core.db``) prepends
        # ``ck_orders_`` itself and re-templates even explicitly named
        # CheckConstraints, which is how the old two-arm form of this CHECK
        # shipped to production as ``ck_orders_ck_orders_actor_exclusive``.
        # Migration 0066 drops that name and re-adds this one clean.
        CheckConstraint(
            "(CASE WHEN user_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN guest_email IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN merchant_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="actor_exclusive",
        ),
        CheckConstraint("total_usd >= 0", name="ck_orders_total_usd_nonneg"),
        CheckConstraint("total_charged >= 0", name="ck_orders_total_charged_nonneg"),
        # Widened by 0073. ``merchant_panel`` is allowed and unreachable: M4's
        # cabinet claims it, nothing writes it yet, and a second migration for
        # one string literal would be waste.
        CheckConstraint(
            "source IN ('web', 'miniapp', 'bot', 'unknown', 'merchant_api', 'merchant_panel')",
            name="ck_orders_source_known",
        ),
        CheckConstraint("purpose IN ('catalog', 'wallet_topup')", name="ck_orders_purpose_known"),
    )


class OrderItem(Base):
    """A single line on an order, with frozen unit price and filled form data."""

    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    sku_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("skus.id", ondelete="RESTRICT"),
        nullable=False,
    )
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    #: This line's share of the order's affiliate discount, in USD.
    #:
    #: The discount is an order-level number, but revenue and margin are
    #: computed per line (``orders.revenue``). Distributing it down to here is
    #: what lets those expressions subtract it once and make every report —
    #: total, per brand, per product — correct without editing each one.
    discount_usd: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, server_default=text("0"), default=Decimal("0")
    )
    # What this line was priced at, frozen at checkout (ADR-0051). On a
    # variable-amount line ``unit_price_usd`` is only the face value the
    # customer chose; the markup that turned it into money lives in
    # ``rate_multiplier``, and reading that from the live SKU meant an admin
    # editing the margin revalued every past order. NULL where it does not
    # apply — a fixed line has no multiplier, an override-priced line and a
    # USD order never touched a rate — and NULL on an old row means "not
    # recorded", which ``orders.revenue`` resolves against the SKU.
    rate_multiplier: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    # What this line cost us, frozen at checkout — the same treatment ADR-0051
    # gave ``rate_multiplier``, on the column it did not cover. ``Sku.cost_usdt``
    # is live: the hourly supplier-price job rewrites it as upstream prices
    # move, so valuing a sale against it re-priced every past order of that SKU
    # every time the supplier moved. NULL on rows written before this column
    # existed, which ``orders.revenue`` resolves against the price history.
    #
    # INTERNAL. Never add this to an ``*Out`` schema that a customer can reach:
    # it is our purchase price, and the order response it would ride on is
    # public to the buyer. ``OrderItemOut`` lists its fields explicitly and
    # forbids extras, so the leak has to be written deliberately — do not.
    cost_usdt: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    # What the merchant said they expected to pay, frozen at order time
    # (spec item 3b, ADR-0071). **Merchant lines only**: retail has no quote,
    # so NULL here means "not a merchant order" or "placed before 0072", and
    # ``orders.merchant_id IS NOT NULL`` is what tells those apart.
    #
    # It decides nothing. ``expected_price`` is an accept/reject tolerance and
    # never a bid (``merchants.pricing.price_to_charge``), so the price charged
    # is ``unit_price_usd`` whatever this says; this column exists so that a
    # reseller disputing a charge can be answered from a row, and so the drift
    # between the two is measurable at all. Before it, ``expected_price``
    # survived only inside a one-way SHA-256 request digest.
    #
    # INTERNAL, like ``cost_usdt`` beside it — but for the opposite reason.
    # This is the merchant's own number, not ours; publishing it back to them
    # would be harmless and is simply not in the ``/merchant/v1`` contract, and
    # adding it to a customer-facing ``*Out`` schema would put one buyer's
    # figure on another surface. ``OrderItemOut`` lists its fields explicitly.
    merchant_expected_price_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    fulfillment_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    fulfillment_state: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="pending"
    )
    supplier_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    order: Mapped[Order] = relationship(back_populates="items")
    sku: Mapped[Sku] = relationship("Sku", lazy="raise")

    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_order_items_qty_positive"),
        CheckConstraint("unit_price_usd > 0", name="ck_order_items_price_positive"),
        CheckConstraint(
            "rate_multiplier IS NULL OR rate_multiplier > 0",
            name="ck_order_items_rate_multiplier_positive",
        ),
        CheckConstraint("fx_rate IS NULL OR fx_rate > 0", name="ck_order_items_fx_rate_positive"),
        CheckConstraint(
            "cost_usdt IS NULL OR cost_usdt > 0", name="ck_order_items_cost_usdt_positive"
        ),
    )


class OrderEvent(Base):
    """Append-only audit log per order. The outbox reads from here later."""

    __tablename__ = "order_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    actor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    order: Mapped[Order] = relationship(back_populates="events")


__all__ = ["Order", "OrderEvent", "OrderItem"]
