"""Push notifications to the mobile app: the buyer's devices and the queue of messages."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class PushDevice(Base):
    """One installed app that may be pushed to, by its Expo push token.

    A token belongs to one install; when another account signs in on the same phone the row
    moves to that account. ``disabled_at`` is set on sign-out, or when Expo says the token no
    longer reaches anything (``DeviceNotRegistered``); a disabled row is never pushed to.
    """

    __tablename__ = "push_devices"
    __table_args__ = (
        UniqueConstraint("token", name="uq_push_devices_token"),
        CheckConstraint("platform IN ('ios', 'android')", name="platform_known"),
        Index(
            "ix_push_devices_user_active",
            "user_id",
            postgresql_where=text("disabled_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(String(200), nullable=False)
    platform: Mapped[str] = mapped_column(String(8), nullable=False)
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: ``signed_out`` or ``not_registered``.
    disabled_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PushMessage(Base):
    """One message to one device. The worker sends these; a scheduler job reads the receipts.

    ``dedupe_key`` (``<kind>:<order id>``) is unique per device, so an order passing through
    ``delivered`` twice still pushes once.
    """

    __tablename__ = "push_messages"
    __table_args__ = (
        UniqueConstraint("device_id", "dedupe_key", name="uq_push_messages_device_id_dedupe_key"),
        CheckConstraint("status IN ('pending', 'sent', 'failed', 'skipped')", name="status_known"),
        CheckConstraint("attempts >= 0", name="attempts_nonneg"),
        Index(
            "ix_push_messages_pending",
            "next_attempt_at",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_push_messages_receipt_due",
            "sent_at",
            postgresql_where=text("status = 'sent' AND receipt_checked_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    device_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("push_devices.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(String(240), nullable=False)
    #: Handed to the app with the message: what to open when it is tapped.
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    #: NOT NULL on purpose: the claim filters ``next_attempt_at <= now()``, which a NULL fails.
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    ticket_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: ``ok``, ``error`` or ``expired`` (no receipt within a day).
    receipt_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    receipt_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
