"""Inventory + sourcing skeleton.

inventory_codes, inventory_uploads, sku_sourcing_rules. See ADR-0015.

Revision ID: 0010_inventory_sourcing_init
Revises: 0009_wallet_init
Create Date: 2026-05-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_inventory_sourcing_init"
down_revision: str | None = "0009_wallet_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CODE_STATES = ("available", "reserved", "issued", "voided")
_SOURCING_MODES = ("auto", "force_inventory", "force_supplier")


def upgrade() -> None:
    op.create_table(
        "inventory_codes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "sku_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("skus.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("code_ciphertext", postgresql.BYTEA(), nullable=False),
        sa.Column("code_nonce", postgresql.BYTEA(), nullable=False),
        sa.Column("code_hash", sa.CHAR(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column(
            "order_item_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("order_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("state IN " + repr(_CODE_STATES), name="ck_inventory_codes_state"),
        sa.UniqueConstraint("sku_id", "code_hash", name="uq_inventory_codes_sku_hash"),
    )
    op.create_index(
        "ix_inventory_codes_available",
        "inventory_codes",
        ["sku_id", "created_at"],
        postgresql_where=sa.text("state = 'available'"),
    )
    op.create_index(
        "ix_inventory_codes_order_item",
        "inventory_codes",
        ["order_item_id"],
        postgresql_where=sa.text("order_item_id IS NOT NULL"),
    )

    op.create_table(
        "inventory_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "sku_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("skus.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("succeeded", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_inventory_uploads_sku", "inventory_uploads", ["sku_id"])

    op.create_table(
        "sku_sourcing_rules",
        sa.Column(
            "sku_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("skus.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column("supplier_slug", sa.String(32), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("mode IN " + repr(_SOURCING_MODES), name="ck_sku_sourcing_rules_mode"),
        sa.CheckConstraint(
            "(mode = 'force_supplier' AND supplier_slug IS NOT NULL) OR mode <> 'force_supplier'",
            name="ck_sku_sourcing_rules_supplier_required",
        ),
    )


def downgrade() -> None:
    op.drop_table("sku_sourcing_rules")
    op.drop_index("ix_inventory_uploads_sku", table_name="inventory_uploads")
    op.drop_table("inventory_uploads")
    op.drop_index("ix_inventory_codes_order_item", table_name="inventory_codes")
    op.drop_index("ix_inventory_codes_available", table_name="inventory_codes")
    op.drop_table("inventory_codes")
