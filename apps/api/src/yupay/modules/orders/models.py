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
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    total_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    total_charged: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    fx_snapshot_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("fx_snapshots.id", ondelete="RESTRICT"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
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
        order_by="OrderItem.created_at",
    )
    events: Mapped[list[OrderEvent]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="OrderEvent.created_at",
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
        CheckConstraint(
            "(user_id IS NULL) <> (guest_email IS NULL)",
            name="ck_orders_actor_exclusive",
        ),
        CheckConstraint("total_usd >= 0", name="ck_orders_total_usd_nonneg"),
        CheckConstraint("total_charged >= 0", name="ck_orders_total_charged_nonneg"),
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
