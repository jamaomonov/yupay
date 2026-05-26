"""SQLAlchemy ORM for the ``integrations`` module.

Two tables:

- ``sku_supplier_mapping`` — *what* a YuPay SKU corresponds to at a given
  supplier. Composite PK ``(sku_id, supplier_slug)`` so a SKU can be mapped to
  several suppliers (future fallback chains: Steam → G2B, etc).
- ``supplier_catalog_cache`` — opportunistic cache of the supplier's own
  catalog (products / games). Used only as autocomplete-bait in the admin UI
  when editing the mapping. The source of truth at fulfilment time is
  ``sku_supplier_mapping``.

See ADR-0019.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class SkuSupplierMapping(Base):
    """Mapping between one YuPay SKU and one supplier's external product id."""

    __tablename__ = "sku_supplier_mapping"

    sku_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("skus.id", ondelete="CASCADE"),
        primary_key=True,
    )
    supplier_slug: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    external_product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    external_variant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    extra: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('voucher','game')",
            name="ck_sku_supplier_mapping_kind",
        ),
        CheckConstraint("quantity > 0", name="ck_sku_supplier_mapping_quantity_positive"),
        Index(
            "ix_sku_supplier_mapping_lookup",
            "supplier_slug",
            "external_product_id",
        ),
    )


class SupplierCatalogCache(Base):
    """Cached snapshot of a supplier's external catalog item.

    Populated by ``POST /admin/integrations/{supplier}/sync-catalog``;
    used as autocomplete in the mapping UI. Not used in the order-fulfilment
    path — never trust this for live prices.
    """

    __tablename__ = "supplier_catalog_cache"

    supplier_slug: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('voucher','game','game_denom')",
            name="ck_supplier_catalog_cache_kind",
        ),
    )


__all__ = ["SkuSupplierMapping", "SupplierCatalogCache"]
