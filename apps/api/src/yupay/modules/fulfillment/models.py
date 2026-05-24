"""SQLAlchemy ORM for the ``fulfillment`` module. See ADR-0013."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yupay.core.db import Base


class FulfillmentTask(Base):
    """One task per order_item — the unit the saga drives through its FSM."""

    __tablename__ = "fulfillment_tasks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("order_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    supplier: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    # Manual fulfilment audit: the admin id that completed or rejected the
    # task and an optional free-text note. We keep these as columns (not in
    # ``extra_metadata``) to avoid colliding with merged supplier metadata.
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attempts: Mapped[list[FulfillmentAttempt]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="FulfillmentAttempt.created_at",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','in_progress','succeeded','failed','cancelled')",
            name="ck_fulfillment_tasks_status",
        ),
        CheckConstraint("attempts_count >= 0", name="ck_fulfillment_tasks_attempts_nonneg"),
        UniqueConstraint("order_item_id", name="uq_fulfillment_tasks_order_item"),
    )


class FulfillmentAttempt(Base):
    """Audit row for each interaction with a supplier."""

    __tablename__ = "fulfillment_attempts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("fulfillment_tasks.id", ondelete="CASCADE"),
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

    task: Mapped[FulfillmentTask] = relationship(back_populates="attempts")


class Delivery(Base):
    """The artifact handed to the customer for a fulfilled order item."""

    __tablename__ = "deliveries"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    order_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("order_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    artifact_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    artifact: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (UniqueConstraint("order_item_id", name="uq_deliveries_order_item"),)


__all__ = ["Delivery", "FulfillmentAttempt", "FulfillmentTask"]
