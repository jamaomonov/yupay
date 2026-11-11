"""USDT (TRC20) top-up: the switch row, exact-amount reservations, the chain journal (ADR-0104).

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
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class UsdtSettings(Base):
    """The single row of USDT switches: who may top up, and the amount bounds."""

    __tablename__ = "usdt_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="off")
    allowlist_merchant_ids: Mapped[list[str]] = mapped_column(
        ARRAY(UUID(as_uuid=False)), nullable=False, server_default="{}"
    )
    min_amount_usd: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default="10"
    )
    max_amount_usd: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default="50000"
    )
    updated_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("mode IN ('off','allowlist','all')", name="mode"),
        CheckConstraint("min_amount_usd > 0 AND max_amount_usd >= min_amount_usd", name="bounds"),
    )


NETWORK_CHECK = "network IN ('trc20','bep20','erc20')"


class UsdtNetwork(Base):
    """One chain's receiving address, switch and poll cursor (``networks.py`` has the facts)."""

    __tablename__ = "usdt_networks"

    network: Mapped[str] = mapped_column(String(8), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    #: The owner's address on this chain (TRON base58 or checksummed ``0x``).
    #: Public; the keys are never ours.
    address: Mapped[str | None] = mapped_column(String(42), nullable=True)
    #: Where the next poll starts: TRON — block time in ms; EVM — the last
    #: block number read. A new address resets it to "now" / the chain head.
    cursor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: TRON only: resume at the cursor itself rather than ten minutes before
    #: it — after a page-capped read and after an address change.
    cursor_exact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    updated_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (CheckConstraint(NETWORK_CHECK, name="network"),)


class UsdtReservation(Base):
    """An exact USDT amount held for one reseller for 30 minutes."""

    __tablename__ = "usdt_reservations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    number: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    merchant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("merchants.id"), nullable=False
    )
    network: Mapped[str] = mapped_column(String(8), nullable=False)
    address: Mapped[str] = mapped_column(String(42), nullable=False)
    amount_usdt: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
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
        CheckConstraint("amount_usdt > 0", name="amount"),
        CheckConstraint(NETWORK_CHECK, name="network"),
        # The rule the design rests on: one open amount per receiving address.
        # Per address, not per chain: BEP20 and ERC20 share one 0x address, and
        # a reseller who reserved on one but sent on the other must not pay
        # someone else's hold of the same amount.
        Index(
            "uq_usdt_reservations_open_amount",
            "address",
            "amount_usdt",
            unique=True,
            postgresql_where=text("holds_amount"),
        ),
        Index(
            "uq_usdt_reservations_one_pending",
            "merchant_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "uq_usdt_reservations_idem",
            "merchant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_usdt_reservations_sweep", "status", "expires_at"),
        Index("ix_usdt_reservations_match", "network", "amount_usdt", "created_at"),
    )


class UsdtIncoming(Base):
    """One confirmed USDT transfer to our address, and what became of it."""

    __tablename__ = "usdt_incoming"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    network: Mapped[str] = mapped_column(String(8), nullable=False)
    #: Not unique alone: one transaction can carry several USDT events to us
    #: (a batch payout). ``event_key`` tells them apart: the log index on EVM
    #: chains; sender + raw value on TRON, where TronGrid gives no index.
    tx_id: Mapped[str] = mapped_column(String(66), nullable=False)
    event_key: Mapped[str] = mapped_column(String(96), nullable=False)
    from_address: Mapped[str] = mapped_column(String(42), nullable=False)
    to_address: Mapped[str] = mapped_column(String(42), nullable=False)
    #: Exact as the chain sent it: USDT on BNB Chain has 18 decimals.
    amount_usdt: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    block_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    reservation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    #: The reseller credited by hand (``result='manual'``).
    merchant_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "result IN ('matched','unmatched','ignored','manual','dismissed')", name="result"
        ),
        CheckConstraint(NETWORK_CHECK, name="network"),
        UniqueConstraint("network", "tx_id", "event_key", name="uq_usdt_incoming_event"),
        Index("ix_usdt_incoming_block_at", "block_at"),
        Index("ix_usdt_incoming_result", "result"),
    )


__all__ = ["UsdtIncoming", "UsdtNetwork", "UsdtReservation", "UsdtSettings"]
