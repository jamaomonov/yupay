"""SQLAlchemy ORM for the ``uzum`` module.

``UzumTransaction`` is the source of truth for Uzum Bank's Merchant API
transaction state machine — status ``CREATED``, ``CONFIRMED``, ``REVERSED``,
``FAILED``. It is keyed on ``trans_id`` (Uzum's own transaction id) so every
Merchant API method (``/create``, ``/confirm``, ``/reverse``, ``/check``,
``/status``) is idempotent against replays. This is the inverted-webhook twin
of :mod:`yupay.modules.payme.models` — see ``docs/superpowers/specs/
2026-07-22-uzum-merchant-api-design.md`` §5 for the full data-model rationale.
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
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class UzumTransaction(Base):
    """One Uzum Bank transaction, mirroring Uzum's own transaction record.

    ``create_time`` is epoch-milliseconds as sent by Uzum (not app-generated) —
    it is echoed back verbatim in ``/check`` and ``/status`` responses.
    ``confirm_time``/``reverse_time`` stay ``NULL`` until the corresponding
    Merchant API method is called.
    """

    __tablename__ = "uzum_transactions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    trans_id: Mapped[str] = mapped_column(String(64), nullable=False)
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
    amount_sum: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    service_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    create_time: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    confirm_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reverse_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    payment_source: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint("trans_id", name="uq_uzum_transactions_trans_id"),
        CheckConstraint(
            "status IN ('CREATED', 'CONFIRMED', 'REVERSED', 'FAILED')",
            name="ck_uzum_transactions_status",
        ),
        Index("ix_uzum_transactions_order", "order_id"),
    )


__all__ = ["UzumTransaction"]
