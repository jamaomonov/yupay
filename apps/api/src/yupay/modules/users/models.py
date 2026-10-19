"""SQLAlchemy ORM models for the ``users`` module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yupay.core.db import Base


class User(Base):
    """A YuPay account.

    A user may have either an email, a Telegram link, or both. Guest checkouts do **not**
    create rows here — they use ``auth_sessions(kind='guest')`` only.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("purchase_limit_usd >= 0", name="purchase_limit_usd_non_negative"),
        CheckConstraint(
            "signup_source IN ('web', 'miniapp', 'mobile', 'unknown')",
            name="signup_source_known",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    email: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Where this customer's codes go. Separate from ``email`` on purpose: that
    # one is the login identity (unique, resolved by the auth service), so a
    # settings screen must never write to it. This is a mailing address —
    # never a credential, never looked up to find an account.
    delivery_email: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    locale: Mapped[str] = mapped_column(String(8), nullable=False, server_default="ru")
    # Preferred display currency for prices & balances across the storefront +
    # miniapp. The customer can change it from Settings; persisted server-side
    # so it survives device switches (Telegram desktop ↔ phone).
    display_currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default="USD")
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # `text`, not `varchar(n)`: a URL has no natural length bound, and 1024
    # was a guess reality exceeded (a real Google avatar URL, ~2026-09-18,
    # StringDataRightTruncationError on INSERT — see migration 0083). The
    # application-level guard against something truly absurd lives in
    # `yupay.modules.users.identity_guard`, not here.
    photo_url: Mapped[str | None] = mapped_column(Text(), nullable=True)
    # List of role strings — e.g. ``["admin"]``. See ADR-0010.
    roles: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    # Where the account was opened (migration 0103): the surface that sent the first
    # sign-in, from ``X-Yupay-Surface`` (the mini app's own route always says
    # ``miniapp``). Client-declared, like ``orders.source`` — an operator's "where did
    # this customer come from", never an authorisation input. Set once at creation,
    # never on a later sign-in from somewhere else.
    signup_source: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'unknown'"), default="unknown"
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

    # --- Ban (ADR-0045) ---
    # A timestamp rather than a boolean: "since when" is the first thing asked
    # when a customer disputes a suspension, and it costs nothing to keep.
    banned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ban_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Who pressed the button. A ban cuts off a paying customer, so it should
    # never be an anonymous act. SET NULL: the record outlives the admin account.
    banned_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # --- Purchase policy (orders.account_policy, 2026-10-11) ---
    # Lifetime cap on what this account may buy before orders go to review:
    # its own orders plus guest orders under its email. NULL = no cap.
    purchase_limit_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Trusted accounts skip every review rule and the pre-charge veto.
    trusted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trusted_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    telegram_link: Mapped[TelegramLink | None] = relationship(
        back_populates="user",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    steam_link: Mapped[SteamLink | None] = relationship(
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
    # Set when a Telegram delivery (bot message or broadcast) comes back as
    # "bot was blocked by the user"; cleared implicitly by re-linking. Lets the
    # broadcasts module skip known-blocked recipients without a live send attempt.
    bot_blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="telegram_link", lazy="joined")


__all__ = ["TelegramLink", "User"]


class SteamLink(Base):
    """Maps a YuPay :class:`User` to a Steam identity.

    Same shape as :class:`TelegramLink` and for the same reason: Steam's
    OpenID hands us only a steamid64 (no email), so the link IS the account
    identity, and keeping Steam fields in their own table unblocks "link a
    Steam account to an existing user" later without schema churn.
    """

    __tablename__ = "steam_links"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    steam_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    persona_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="steam_link", lazy="joined")
