"""Persist the margin a SKU is meant to hold above its supplier cost.

price_usd and cost_usdt already existed, but nothing recorded the
*relationship* between them the admin actually intended — the hourly
supplier price-refresh (integrations.price_refresh) updated cost_usdt on
every upstream move and left price_usd untouched, so a SKU nobody was
actively watching could end up selling below cost the moment the supplier
raised their price. margin_percent lets that refresh re-derive price_usd
from the saved margin instead.

Backfilled from every row's *current* price/cost ratio rather than left
NULL — the point is protecting the SKUs nobody is actively re-saving, so
waiting for an admin to open and re-save each one first would defeat it.
NULL stays reserved for the rows that genuinely never had a cost on file
(cost_usdt IS NULL): there is no ratio to compute, and refresh already
treats a NULL margin as "leave price_usd alone", identical to its
pre-migration behaviour.

Revision ID: 0043_sku_margin_percent
Revises: 0042_sku_supplier_stock
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0043_sku_margin_percent"
down_revision: str | None = "0042_sku_supplier_stock"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("skus", sa.Column("margin_percent", sa.Numeric(10, 4), nullable=True))
    op.create_check_constraint(
        "ck_skus_margin_percent_above_minus_100",
        "skus",
        "margin_percent IS NULL OR margin_percent > -100",
    )
    op.execute(
        """
        UPDATE skus
        SET margin_percent = ROUND(((price_usd - cost_usdt) / cost_usdt) * 100, 4)
        WHERE cost_usdt IS NOT NULL AND cost_usdt > 0
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_skus_margin_percent_above_minus_100", "skus", type_="check")
    op.drop_column("skus", "margin_percent")
