"""P2P card transfers: cards, exact-amount reservations, the incoming journal (spec §5.2).

Check-constraint names are bare suffixes: ``core.db.NAMING_CONVENTION`` adds
the ``ck_<table>_`` prefix itself.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class P2PCard(Base):
    """A card resellers transfer to. ``pan_*`` is the sealed full number."""

    __tablename__ = "p2p_cards"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    pan_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    pan_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    pan_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    holder_name: Mapped[str] = mapped_column(String(128), nullable=False)
    network: Mapped[str] = mapped_column(String(16), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    min_amount_uzs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10000")
    max_amount_uzs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10000000")
    daily_limit_uzs: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)

    __table_args__ = (
        CheckConstraint("network IN ('humo','uzcard')", name="network"),
        CheckConstraint("min_amount_uzs > 0 AND max_amount_uzs >= min_amount_uzs", name="bounds"),
    )


class P2PReservation(Base):
    """An exact amount held on a card: for one reseller for five minutes, or for
    one storefront order until that order expires (ADR-0097)."""

    __tablename__ = "p2p_reservations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    number: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    card_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("p2p_cards.id"), nullable=False
    )
    amount_uzs: Mapped[int] = mapped_column(BigInteger, nullable=False)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)
    merchant_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("merchants.id"), nullable=True
    )
    # A storefront order this reservation is the payment intent of
    # (``purpose='order'``, ADR-0097). Exactly one of ``merchant_id`` /
    # ``order_id`` is set, by ``purpose``.
    order_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id"), nullable=True
    )
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    fx_snapshot_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    holds_amount: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantine_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    incoming_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('pending','paid','expired','cancelled')", name="status"),
        CheckConstraint("purpose IN ('merchant_deposit','order')", name="purpose"),
        CheckConstraint("amount_uzs > 0", name="amount"),
        # The rule the whole design rests on: one open amount per card.
        Index(
            "uq_p2p_reservations_open_amount",
            "card_id",
            "amount_uzs",
            unique=True,
            postgresql_where=text("holds_amount"),
        ),
        Index(
            "uq_p2p_reservations_one_pending",
            "merchant_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "uq_p2p_reservations_one_pending_order",
            "order_id",
            unique=True,
            postgresql_where=text("status = 'pending' AND order_id IS NOT NULL"),
        ),
        Index(
            "uq_p2p_reservations_idem",
            "merchant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_p2p_reservations_sweep", "status", "expires_at"),
    )


class P2PIncoming(Base):
    """One @HUMOcardbot notification and what it was credited to."""

    __tablename__ = "p2p_incoming"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    business_connection_id: Mapped[str] = mapped_column(String(128), nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_uzs: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    source_text: Mapped[str | None] = mapped_column(String(128), nullable=True)
    card_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    bank_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    chain_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    reservation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "business_connection_id", "telegram_message_id", name="uq_p2p_incoming_message"
        ),
        CheckConstraint("kind IN ('credit','debit','unparsed')", name="kind"),
        CheckConstraint("result IN ('matched','unmatched','ignored')", name="result"),
        Index("ix_p2p_incoming_card_time", "card_last4", "bank_time"),
        Index("ix_p2p_incoming_received", "received_at"),
    )


class P2PSettings(Base):
    """The single row of P2P switches (``steam_gift_settings`` template)."""

    __tablename__ = "p2p_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="off")
    allowlist_merchant_ids: Mapped[list[str]] = mapped_column(
        ARRAY(UUID(as_uuid=False)), nullable=False, server_default="{}"
    )
    humo_bot_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # The owner's own Telegram id (entered by an admin) and the Business
    # connection Telegram reported for that owner (captured by the intake).
    # Only messages arriving through that one connection are read.
    owner_telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    business_connection_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("mode IN ('off','allowlist','all')", name="mode"),
    )


__all__ = ["P2PCard", "P2PIncoming", "P2PReservation", "P2PSettings"]
