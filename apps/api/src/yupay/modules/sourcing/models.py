"""SQLAlchemy ORM for the ``sourcing`` module. See ADR-0015."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, text
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


class SourcingSettings(Base):
    """The single row of smart-sourcing switches (ADR-0108), edited in the admin.

    ``failover_mode`` hands a task a supplier refused (money back) to the next
    cheapest one: ``off`` (the pre-ADR behaviour), ``retail`` or ``all`` (resellers
    too). The margins are percent of what the buyer paid that must remain after the
    new supplier's cost; ``failover_max_step_pct`` caps how much dearer the new
    supplier may be than the line's original cost.
    """

    __tablename__ = "sourcing_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    failover_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="off")
    failover_min_margin_retail_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default="3"
    )
    failover_min_margin_b2b_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default="0"
    )
    failover_max_step_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default="6"
    )
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        CheckConstraint(
            "failover_mode IN ('off','retail','all')", name="ck_sourcing_settings_failover_mode"
        ),
    )


__all__ = ["SkuSourcingRule", "SourcingSettings"]
