"""SQLAlchemy ORM for the ``inventory`` module. See ADR-0015."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class InventoryCode(Base):
    """One voucher / coupon code at rest. Cleartext is never stored."""

    __tablename__ = "inventory_codes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    sku_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("skus.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    code_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    code_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    order_item_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("order_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    reserved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    uploaded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('available','reserved','issued','voided')",
            name="ck_inventory_codes_state",
        ),
        UniqueConstraint("sku_id", "code_hash", name="uq_inventory_codes_sku_hash"),
    )


class InventoryUpload(Base):
    """Audit row per bulk-upload."""

    __tablename__ = "inventory_uploads"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    sku_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("skus.id", ondelete="RESTRICT"),
        nullable=False,
    )
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    succeeded: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


__all__ = ["InventoryCode", "InventoryUpload"]
