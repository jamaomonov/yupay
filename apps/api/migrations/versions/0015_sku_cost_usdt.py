"""Add ``skus.cost_usdt`` for supplier COGS.

YuPay pays suppliers in USDT. Pricing the catalog is one number; what we
actually paid for the SKU is another. Storing both lets the admin compute
margin and lets the catalog generate UZS prices (cost × current FX rate)
without confusing display currency with cost currency.

The column is nullable so existing rows keep working; new SKUs are
expected to set it explicitly.

Revision ID: 0015_sku_cost_usdt
Revises: 0014_admin_saved_segments
Create Date: 2026-05-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_sku_cost_usdt"
down_revision: str | None = "0014_admin_saved_segments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skus",
        sa.Column("cost_usdt", sa.Numeric(20, 6), nullable=True),
    )
    op.create_check_constraint(
        "ck_skus_cost_usdt_positive",
        "skus",
        "cost_usdt IS NULL OR cost_usdt > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_skus_cost_usdt_positive", "skus", type_="check")
    op.drop_column("skus", "cost_usdt")
