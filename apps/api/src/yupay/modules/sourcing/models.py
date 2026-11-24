"""SQLAlchemy ORM for the ``sourcing`` module. See ADR-0015."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    text,
)
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
    # The hourly smart-routing job may move ``supplier_slug`` (ADR-0108). The mode
    # stays ``force_supplier``; an operator's own save clears this (a pin).
    managed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
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
    #: Smart routing: ``off`` / ``shadow`` (log only) / ``on``.
    smart_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="off")
    smart_switch_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default="1"
    )
    smart_dwell_hours: Mapped[int] = mapped_column(Integer, nullable=False, server_default="6")
    smart_stock_step_pct: Mapped[Decimal] = mapped_column(
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
        CheckConstraint(
            "smart_mode IN ('off','shadow','on')", name="ck_sourcing_settings_smart_mode"
        ),
    )


class SourcingSwitchLog(Base):
    """One switch the smart-routing job made, or in ``shadow`` would have made."""

    __tablename__ = "sourcing_switch_log"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    sku_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("skus.id", ondelete="CASCADE"), nullable=False
    )
    from_supplier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_supplier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    from_cost_usdt: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    to_cost_usdt: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    #: ``cheaper`` / ``unavailable`` / ``blocked`` (nothing acceptable to move to).
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class SourcingQuarantine(Base):
    """A supplier sitting out one SKU after repeated failures, until ``until``."""

    __tablename__ = "sourcing_quarantine"

    sku_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("skus.id", ondelete="CASCADE"), primary_key=True
    )
    supplier_slug: Mapped[str] = mapped_column(String(32), primary_key=True)
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    strikes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


__all__ = [
    "SkuSourcingRule",
    "SourcingQuarantine",
    "SourcingSettings",
    "SourcingSwitchLog",
]
