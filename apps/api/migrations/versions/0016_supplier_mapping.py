"""Integrations: sku_supplier_mapping + supplier_catalog_cache.

First real supplier integration (G2Bulk) lands in a follow-up PR; this
migration only sets up the persistent storage. See ADR-0019.

Revision ID: 0016_supplier_mapping
Revises: 0015_sku_cost_usdt
Create Date: 2026-05-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_supplier_mapping"
down_revision: str | None = "0015_sku_cost_usdt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_MAPPING_KINDS = ("voucher", "game")
_CATALOG_KINDS = ("voucher", "game", "game_denom")


def upgrade() -> None:
    op.create_table(
        "sku_supplier_mapping",
        sa.Column(
            "sku_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("skus.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("supplier_slug", sa.String(32), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("external_product_id", sa.String(128), nullable=False),
        sa.Column("external_variant_id", sa.String(128), nullable=True),
        sa.Column(
            "quantity",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "extra",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "kind IN " + repr(_MAPPING_KINDS),
            name="ck_sku_supplier_mapping_kind",
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_sku_supplier_mapping_quantity_positive",
        ),
    )
    op.create_index(
        "ix_sku_supplier_mapping_lookup",
        "sku_supplier_mapping",
        ["supplier_slug", "external_product_id"],
    )

    op.create_table(
        "supplier_catalog_cache",
        sa.Column("supplier_slug", sa.String(32), primary_key=True),
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("external_id", sa.String(128), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column(
            "raw",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "kind IN " + repr(_CATALOG_KINDS),
            name="ck_supplier_catalog_cache_kind",
        ),
    )


def downgrade() -> None:
    op.drop_table("supplier_catalog_cache")
    op.drop_index("ix_sku_supplier_mapping_lookup", table_name="sku_supplier_mapping")
    op.drop_table("sku_supplier_mapping")
