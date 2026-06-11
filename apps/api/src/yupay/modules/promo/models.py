"""SQLAlchemy ORM for the ``promo`` module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class PromoCode(Base):
    """A fixed-denomination gift code. Crediting target is always the
    customer's ``user_wallet`` in :attr:`currency` — visible and spendable
    immediately (see ADR-0029)."""

    __tablename__ = "promo_codes"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_promo_codes_amount_positive"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    # Stored uppercase; lookups normalise the user's input the same way.
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    # NULL ⇒ unlimited total redemptions (still one per user).
    max_redemptions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class PromoRedemption(Base):
    """One user's redemption of one code. ``UNIQUE(promo_code_id, user_id)``
    is the DB-level once-per-user guarantee."""

    __tablename__ = "promo_redemptions"
    __table_args__ = (
        UniqueConstraint("promo_code_id", "user_id", name="uq_promo_redemptions_code_user"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    promo_code_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("promo_codes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # The ledger posting that carried the credit — the audit trail.
    transaction_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("wallet_transactions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Client retry token; lets a timeout-retry replay the original success.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


__all__ = ["PromoCode", "PromoRedemption"]
