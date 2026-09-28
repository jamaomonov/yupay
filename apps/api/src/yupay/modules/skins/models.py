"""SQLAlchemy ORM for the ``skins`` module (ADR-0093).

- :class:`SkinItem` — one row per ``(market_hash_name, phase)``: our own
  identity, taxonomy and image (from ByMykel/CSGO-API, daily) plus the
  Waxpeer side folded on every five minutes by ``skins.prices``.
  ``phase`` is ``''`` when the item has none — never NULL, so the unique
  constraint below holds.
- :class:`SkinPricingRules` — singleton (``id = 1``) holding the whole
  pricing document as JSONB (validated by ``pricing.PricingRules`` on every
  read and write); the shape of ``gifts.models.SteamGiftSettings`` with a
  document instead of two numbers.
- :class:`SkinSearchAlias` — ``alias -> text`` expansions applied to a
  search query before the trigram match («ак» -> ``ak-47``).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class SkinItem(Base):
    """One sellable CS2 item at one wear (and one Doppler phase)."""

    __tablename__ = "skin_items"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    market_hash_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("''"))
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    weapon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skin: Mapped[str | None] = mapped_column(String(128), nullable=True)
    exterior: Mapped[str | None] = mapped_column(String(2), nullable=True)
    stattrak: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    souvenir: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    rarity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rarity_color: Mapped[str | None] = mapped_column(String(9), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    min_float: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)
    max_float: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)
    paint_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: ``'bymykel'`` once the daily import has written the row, ``'stub'``
    #: while it only exists because the snapshot named it.
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'stub'"))
    search_text: Mapped[str] = mapped_column(Text, nullable=False)

    # ---- the Waxpeer side (units: 1000 = $1) ----
    steam_price_units: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    min_auto_units: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    count_auto: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    #: Up to ten ``{"listing_id": int, "price_units": int}`` cheapest auto listings.
    cheapest_auto: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    min_all_units: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    count_all: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    price_hash: Mapped[str | None] = mapped_column(String(40), nullable=True)
    prices_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    # ---- per-item pricing overrides (admin, ``PATCH /admin/skins/items/{slug}``) ----
    #: Percentage points added to the bracket margin for this item only.
    margin_override_pp: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    #: A pinned sell price. Honoured only while it covers cost + min margin.
    fixed_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # ---- derived, written by ``repricing.reprice_rows`` (never by hand) ----
    #: Our sell price for the cheapest auto listing — what the card shows and
    #: what every price filter and sort reads. NULL while inactive.
    sell_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    #: Whole percent below Steam, truncated toward zero; NULL without a Steam price.
    discount_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint("market_hash_name", "phase", name="uq_skin_items_name_phase"),
        UniqueConstraint("slug", name="uq_skin_items_slug"),
        Index("ix_skin_items_category_price", "category", "min_auto_units"),
        Index("ix_skin_items_weapon", "weapon"),
        Index("ix_skin_items_active", "active"),
        Index(
            "ix_skin_items_search_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )


class SkinPricingRules(Base):
    """Row 1: the pricing document (``pricing.PricingRules``) an admin edits."""

    __tablename__ = "skin_pricing_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (CheckConstraint("id = 1", name="ck_skin_pricing_rules_singleton"),)


class SkinSearchAlias(Base):
    """``alias`` (lower-case, one token or a phrase) -> ``text`` substituted into a query."""

    __tablename__ = "skin_search_aliases"

    alias: Mapped[str] = mapped_column(String(64), primary_key=True)
    text: Mapped[str] = mapped_column(String(128), nullable=False)


class SkinTrade(Base):
    """One Waxpeer purchase for one order line, mirrored for the order page and for ops.

    ``status`` is Waxpeer's own number (0 processing … 4 sent … 5 completed, 6 failed);
    ``release_date`` appears when the buyer accepts and Steam's 7-day trade protection
    starts (spec §8.1). ``project_id`` is the idempotency key sent to Waxpeer.
    """

    __tablename__ = "skin_trades"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    order_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("order_items.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("fulfillment_tasks.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[str] = mapped_column(String(128), nullable=False)
    waxpeer_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    listing_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    market_hash_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("''"))
    paid_units: Mapped[int] = mapped_column(Integer, nullable=False)
    bought_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    trade_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    send_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_released: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    penalties: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    seller: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint("order_item_id", name="uq_skin_trades_order_item"),
        UniqueConstraint("project_id", name="uq_skin_trades_project"),
        Index("ix_skin_trades_protection", "status", "is_released"),
    )


class SkinTradeLink(Base):
    """A signed-in customer's saved Steam trade link (the token in it is a credential)."""

    __tablename__ = "skin_trade_links"

    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    url: Mapped[str] = mapped_column(String(255), nullable=False)
    steam_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


__all__ = ["SkinItem", "SkinPricingRules", "SkinSearchAlias", "SkinTrade", "SkinTradeLink"]
