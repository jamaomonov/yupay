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
    succeeded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    signature_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)


__all__ = ["Payment", "PaymentAttempt", "PaymentWebhook"]
