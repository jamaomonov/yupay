"""SQLAlchemy ORM models for the ``users`` module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yupay.core.db import Base


class User(Base):
    """A YuPay account.

    A user may have either an email, a Telegram link, or both. Guest checkouts do **not**
    create rows here — they use ``auth_sessions(kind='guest')`` only.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    email: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    locale: Mapped[str] = mapped_column(String(8), nullable=False, server_default="ru")
    # Preferred display currency for prices & balances across the storefront +
    # miniapp. The customer can change it from Settings; persisted server-side
    # so it survives device switches (Telegram desktop ↔ phone).
    display_currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default="USD")
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # List of role strings — e.g. ``["admin"]``. See ADR-0010.
    roles: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    telegram_link: Mapped[TelegramLink | None] = relationship(
        back_populates="user",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class TelegramLink(Base):
    """Maps a YuPay :class:`User` to a Telegram identity.

    1:1 with users at MVP. Splitting into its own table keeps Telegram-specific fields
    isolated and unblocks "link another telegram account" later without schema churn.
    """

    __tablename__ = "telegram_links"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    tg_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    is_premium: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    user: Mapped[User] = relationship(back_populates="telegram_link", lazy="joined")


__all__ = ["TelegramLink", "User"]
