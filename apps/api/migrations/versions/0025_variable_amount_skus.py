"""Variable-amount SKUs: the customer chooses how much to buy.

Steam wallet top-ups are sold by amount, not by denomination, so the price is
computed at checkout instead of read off the row. The CHECK keeps a variable
SKU from existing without the bounds and multiplier that pricing needs.

Revision ID: 0025_variable_amount_skus
Revises: 0024_promo_codes
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_variable_amount_skus"
down_revision: str | None = "0024_promo_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skus",
        sa.Column("variable_amount", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("skus", sa.Column("min_amount_usd", sa.Numeric(20, 6), nullable=True))
    op.add_column("skus", sa.Column("max_amount_usd", sa.Numeric(20, 6), nullable=True))
    op.add_column("skus", sa.Column("rate_multiplier", sa.Numeric(10, 4), nullable=True))
    op.create_check_constraint(
        "ck_skus_variable_amount_complete",
        "skus",
        "NOT variable_amount OR ("
        " min_amount_usd IS NOT NULL AND max_amount_usd IS NOT NULL"
        " AND rate_multiplier IS NOT NULL AND min_amount_usd > 0"
        " AND max_amount_usd >= min_amount_usd AND rate_multiplier > 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_skus_variable_amount_complete", "skus", type_="check")
    op.drop_column("skus", "rate_multiplier")
    op.drop_column("skus", "max_amount_usd")
    op.drop_column("skus", "min_amount_usd")
    op.drop_column("skus", "variable_amount")
