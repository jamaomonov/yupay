"""SQLAlchemy ORM for the ``payme`` module.

``PaymeTransaction`` is the source of truth for Payme's (Paycom) Merchant API
transaction state machine — state ``1`` (created), ``2`` (performed), ``-1``
(cancelled before perform), ``-2`` (cancelled after perform). It is keyed on
``payme_id`` (Payme's own transaction id) so every Merchant API method
(``CreateTransaction``, ``PerformTransaction``, ``CancelTransaction``,
``CheckTransaction``) is idempotent against replays.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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


class PaymeTransaction(Base):
    """One Payme transaction, mirroring Paycom's own transaction record.

    ``create_time``/``perform_time``/``cancel_time`` are epoch-milliseconds as
    sent by Payme (not app-generated timestamps) — they are echoed back
    verbatim in ``CheckTransaction`` responses.
    """

    __tablename__ = "payme_transactions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    payme_id: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payment_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
    )
    amount_tiyin: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[int | None] = mapped_column(Integer, nullable=True)
    create_time: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    perform_time: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cancel_time: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    fiscal_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint("payme_id", name="uq_payme_transactions_payme_id"),
        CheckConstraint("state IN (1, 2, -1, -2)", name="ck_payme_transactions_state"),
        Index("ix_payme_transactions_order", "order_id"),
        Index("ix_payme_transactions_state_create", "state", "create_time"),
    )


__all__ = ["PaymeTransaction"]
