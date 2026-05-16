"""SQLAlchemy ORM for the ``sourcing`` module. See ADR-0015."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class SkuSourcingRule(Base):
    """Per-SKU routing rule for fulfilment. Missing row = ``mode='auto'``."""

    __tablename__ = "sku_sourcing_rules"

    sku_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("skus.id", ondelete="CASCADE"),
        primary_key=True,
    )
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    supplier_slug: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        CheckConstraint(
            "mode IN ('auto','force_inventory','force_supplier')",
            name="ck_sku_sourcing_rules_mode",
        ),
    )


__all__ = ["SkuSourcingRule"]
