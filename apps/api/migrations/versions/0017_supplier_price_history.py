"""``supplier_price_history`` — append-only log of upstream cost changes.

Written by the hourly price refresher and (best-effort) by the
``upsert_mapping`` route. Powers the admin sparkline + alert threshold.

Revision ID: 0017_supplier_price_history
Revises: 0016_supplier_mapping
Create Date: 2026-05-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_supplier_price_history"
down_revision: str | None = "0016_supplier_mapping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_MAPPING_KINDS = ("voucher", "game")


def upgrade() -> None:
    op.create_table(
        "supplier_price_history",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "sku_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("skus.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("supplier_slug", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("external_product_id", sa.String(128), nullable=False),
        sa.Column("external_variant_id", sa.String(128), nullable=True),
        sa.Column("cost_usdt", sa.Numeric(20, 6), nullable=False),
        sa.Column("previous_cost_usdt", sa.Numeric(20, 6), nullable=True),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "kind IN " + repr(_MAPPING_KINDS),
            name="ck_supplier_price_history_kind",
        ),
        sa.CheckConstraint("cost_usdt > 0", name="ck_supplier_price_history_cost_positive"),
    )
    # Hot query: load the last N price points for one SKU ordered by time.
    op.create_index(
        "ix_supplier_price_history_sku_time",
        "supplier_price_history",
        ["sku_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_supplier_price_history_sku_time", table_name="supplier_price_history")
    op.drop_table("supplier_price_history")
