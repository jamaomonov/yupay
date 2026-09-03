"""SQLAlchemy ORM for the ``gifts`` module.

- :class:`SteamGiftSettings` — singleton admin setting: the margin percent
  applied on top of supplier cost for Steam gift packages. ``id`` is pinned
  to ``1`` by a CHECK constraint (see migration ``0064_steam_gifts``); there
  is exactly one row, upserted in place.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class SteamGiftSettings(Base):
    """The one admin-editable margin percent for Steam gift packages.

    Mirrors ``fx.models.FxQuoteSetting``'s shape: a small settings row an
    admin patches through ``PATCH /admin/gifts/settings``, read on the hot
    path via ``gifts.settings.load_margin_percent`` (Redis first, this table
    on a cache miss).
    """

    __tablename__ = "steam_gift_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    margin_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    updated_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        CheckConstraint("margin_percent >= 0", name="ck_steam_gift_settings_margin_nonneg"),
        CheckConstraint("id = 1", name="ck_steam_gift_settings_singleton"),
    )


__all__ = ["SteamGiftSettings"]
