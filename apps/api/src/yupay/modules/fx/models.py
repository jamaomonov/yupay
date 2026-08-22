"""SQLAlchemy ORM for the ``fx`` module.

- :class:`FxRate` — append-only history of fetched rates (used for analytics & debugging).
- :class:`FxSnapshot` — immutable rate locked at order creation. Orders reference snapshot
  rows via FK once the ``orders`` module lands.
- :class:`FxQuoteSetting` — per-quote toggle: live provider vs admin-set rate.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class FxRate(Base):
    """Last-known and historical rates fetched from upstream providers."""

    __tablename__ = "fx_rates"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    base: Mapped[str] = mapped_column(String(8), nullable=False)
    quote: Mapped[str] = mapped_column(String(8), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (CheckConstraint("rate > 0", name="ck_fx_rates_positive"),)


class FxSnapshot(Base):
    """Frozen rate captured at checkout. Referenced by ``orders.fx_snapshot_id``."""

    __tablename__ = "fx_snapshots"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    base: Mapped[str] = mapped_column(String(8), nullable=False)
    quote: Mapped[str] = mapped_column(String(8), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (CheckConstraint("rate > 0", name="ck_fx_snapshots_positive"),)


class FxQuoteSetting(Base):
    """Per-quote admin override: use a typed rate instead of the provider chain.

    One row per quote (USD is always the base). ``manual_rate`` stays stored when
    the toggle is off so flipping back does not lose the last typed number.
    """

    __tablename__ = "fx_quote_settings"

    quote: Mapped[str] = mapped_column(String(8), primary_key=True)
    use_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    manual_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "manual_rate IS NULL OR manual_rate > 0",
            name="ck_fx_quote_settings_rate_positive",
        ),
        CheckConstraint(
            "NOT use_manual OR (manual_rate IS NOT NULL AND manual_rate > 0)",
            name="ck_fx_quote_settings_manual_complete",
        ),
    )


__all__ = ["FxQuoteSetting", "FxRate", "FxSnapshot"]
