"""SQLAlchemy ORM for the ``broadcasts`` module.

An admin composes a :class:`Broadcast` (title, HTML body, optional media) targeting a
cohort of Telegram-linked users; the dispatch job (a later task) fans it out into one
:class:`BroadcastRecipient` row per target and tracks per-user delivery outcome.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yupay.core.db import Base


class Broadcast(Base):
    """An admin-authored message queued for delivery to a cohort of Telegram users."""

    __tablename__ = "broadcasts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    body_html: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    media_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'none'")
    )
    media_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    locale_filter: Mapped[str | None] = mapped_column(String(8), nullable=True)
    disable_web_page_preview: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_recipients: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    recipients: Mapped[list[BroadcastRecipient]] = relationship(
        back_populates="broadcast",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','scheduled','sending','sent','failed','canceled')",
            name="ck_broadcasts_status",
        ),
        CheckConstraint(
            "media_type IN ('none','photo','video','animation','document')",
            name="ck_broadcasts_media_type",
        ),
    )


class BroadcastRecipient(Base):
    """One targeted recipient row per broadcast; tracks per-user delivery outcome."""

    __tablename__ = "broadcast_recipients"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    broadcast_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("broadcasts.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    tg_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default=text("'pending'")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    broadcast: Mapped[Broadcast] = relationship(back_populates="recipients")

    __table_args__ = (
        UniqueConstraint("broadcast_id", "user_id", name="uq_broadcast_recipients_broadcast_user"),
        Index("ix_broadcast_recipients_broadcast_status", "broadcast_id", "status"),
        CheckConstraint(
            "status IN ('pending','sent','failed','blocked')",
            name="ck_broadcast_recipients_status",
        ),
    )


__all__ = ["Broadcast", "BroadcastRecipient"]
