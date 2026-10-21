"""SQLAlchemy ORM for the ``payments`` module. See ADR-0012."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yupay.core.db import Base


class Payment(Base):
    """One payment attempt on an order. An order may have multiple over time."""

    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    intent_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Client retry token; partial UNIQUE (see migration 0023). NULL for old rows
    # and internal callers (simulate-webhook, tests that hit the service layer).
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attempts: Mapped[list[PaymentAttempt]] = relationship(
        back_populates="payment",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="PaymentAttempt.created_at",
    )

    __table_args__ = (CheckConstraint("amount > 0", name="ck_payments_amount_positive"),)


class PaymentAttempt(Base):
    """Audit row for every interaction with a payment provider."""

    __tablename__ = "payment_attempts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    payment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("payments.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    payment: Mapped[Payment] = relationship(back_populates="attempts")


class PaymentWebhook(Base):
    """Idempotent record of an incoming provider webhook."""

    __tablename__ = "payment_webhooks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    signature_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)


class PaymentProviderState(Base):
    """Admin-controlled runtime state for a payment gateway slug.

    Orthogonal to a gateway's config-availability (are the keys set): this row
    lets an operator take a provider offline (`disabled`) or flag it as under
    maintenance (`maintenance`) without a code/config change. Absence of a row
    means `active`. One row per slug — the admin layer writes every slug in a
    logical provider's group together (see ``provider_state.LOGICAL_PROVIDERS``).
    """

    __tablename__ = "payment_provider_states"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    changed_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentReviewLimit(Base):
    """How much a buyer may pay through one provider before a human looks.

    One row per payment slug (``click_miniapp``, not the logical ``click``: the
    two Click kassas carry different risk). A buyer whose settled payments
    through this slug in the last ``window_hours`` — the current one included —
    exceed ``max_amount`` is held for review (``orders.provider_limit``). No row,
    or ``enabled = false``, means no limit. Edited in the admin; migration 0104
    seeds the owner's 90 000 soʻm a day for the mini-app kassa.
    """

    __tablename__ = "payment_review_limits"
    __table_args__ = (
        CheckConstraint("max_amount > 0", name="max_amount_positive"),
        CheckConstraint("window_hours BETWEEN 1 AND 720", name="window_hours_range"),
    )

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    max_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'UZS'"))
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("24"))
    changed_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "Payment",
    "PaymentAttempt",
    "PaymentProviderState",
    "PaymentReviewLimit",
    "PaymentWebhook",
]
