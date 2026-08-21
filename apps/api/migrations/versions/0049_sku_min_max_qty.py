"""Allow a SKU to be sold by integer qty (Telegram Stars: one star = qty 1).

Revision ID: 0049_sku_min_max_qty
Revises: 0048_sku_units
Create Date: 2026-08-21

Downgrade is unsafe if a unit SKU row exists (``amount_unit`` set,
``units_per_usd`` NULL). Run the revert seed (Task 10) before downgrading.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0049_sku_min_max_qty"
down_revision: str | None = "0048_sku_units"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("skus", sa.Column("min_qty", sa.Integer(), nullable=True))
    op.add_column("skus", sa.Column("max_qty", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_skus_qty_bounds_complete",
        "skus",
        "(min_qty IS NULL AND max_qty IS NULL) OR "
        "(min_qty IS NOT NULL AND max_qty IS NOT NULL "
        "AND min_qty >= 1 AND max_qty >= min_qty)",
    )
    op.drop_constraint("ck_skus_amount_unit_complete", "skus", type_="check")
    op.create_check_constraint(
        "ck_skus_amount_unit_complete",
        "skus",
        "(amount_unit IS NULL AND units_per_usd IS NULL) "
        "OR (amount_unit IS NOT NULL AND units_per_usd IS NOT NULL AND units_per_usd > 0) "
        "OR (amount_unit IS NOT NULL AND units_per_usd IS NULL AND min_qty IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_skus_amount_unit_complete", "skus", type_="check")
    op.create_check_constraint(
        "ck_skus_amount_unit_complete",
        "skus",
        "(amount_unit IS NULL AND units_per_usd IS NULL) "
        "OR (amount_unit IS NOT NULL AND units_per_usd IS NOT NULL AND units_per_usd > 0)",
    )
    op.drop_constraint("ck_skus_qty_bounds_complete", "skus", type_="check")
    op.drop_column("skus", "max_qty")
    op.drop_column("skus", "min_qty")
