"""SQLAlchemy ORM for the ``click`` module.

``ClickTransaction`` is the source of truth for Click Shop API's Prepare/
Complete transaction state machine — status ``PREPARED``, ``CONFIRMED``,
``CANCELLED``. It is keyed on ``(click_trans_id, service_id)`` (Click's own
transaction id, scoped per service) so both webhooks (``/prepare``,
``/complete``) are idempotent against replays. This is the inverted-webhook
twin of :mod:`yupay.modules.uzum.models` — see ``docs/superpowers/specs/
2026-07-23-click-shop-api-design.md`` §5 for the full data-model rationale.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class ClickTransaction(Base):
    """One Click Shop API transaction, mirroring Click's own transaction record.

    ``merchant_prepare_id`` is a DB-generated (IDENTITY) integer, not our usual
    UUID string id — Click's Prepare response requires an integer
    ``merchant_prepare_id``, so this column exists purely to hand Click a
    value it accepts. ``prepare_time``/``complete_time``/``cancel_time`` are
    app-generated timestamps set on each transition (unlike Uzum/Payme's
    echoed-back epoch-millisecond fields).
    """

    __tablename__ = "click_transactions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    merchant_prepare_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), nullable=False, unique=True
    )
    click_trans_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    service_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
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
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    click_paydoc_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    prepare_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    complete_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint(
            "click_trans_id", "service_id", name="uq_click_transactions_trans_service"
        ),
        CheckConstraint(
            "status IN ('PREPARED', 'CONFIRMED', 'CANCELLED')",
            name="ck_click_transactions_status",
        ),
        Index("ix_click_transactions_order", "order_id"),
    )


__all__ = ["ClickTransaction"]
