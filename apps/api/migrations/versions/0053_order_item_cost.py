"""Freeze the line's cost at checkout.

Revision ID: 0053_order_item_cost
Revises: 0052_order_purpose
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053_order_item_cost"
down_revision: str | None = "0052_order_purpose"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable and deliberately not backfilled. A reconstructed cost written
    # into this column would be indistinguishable from one recorded at
    # checkout, and ADR-0051 made the same call for ``rate_multiplier``: NULL
    # means "not recorded", which the reporting layer resolves against
    # ``supplier_price_history`` rather than guessing here, permanently.
    op.add_column("order_items", sa.Column("cost_usdt", sa.Numeric(20, 6), nullable=True))
    op.create_check_constraint(
        "ck_order_items_cost_usdt_positive",
        "order_items",
        "cost_usdt IS NULL OR cost_usdt > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_order_items_cost_usdt_positive", "order_items", type_="check")
    op.drop_column("order_items", "cost_usdt")
