"""Skins: stored sell price and discount, so filters and sorts use what the card shows.

Revision ID: 0088_skins_sell_price
Revises: 0087_cs2_skins
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0088_skins_sell_price"
down_revision: str | None = "0087_cs2_skins"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("skin_items", sa.Column("sell_price_usd", sa.Numeric(12, 2), nullable=True))
    op.add_column("skin_items", sa.Column("discount_percent", sa.Integer(), nullable=True))
    op.create_index("ix_skin_items_category_sell", "skin_items", ["category", "sell_price_usd"])
    op.create_index("ix_skin_items_discount", "skin_items", ["discount_percent"])


def downgrade() -> None:
    op.drop_index("ix_skin_items_discount", table_name="skin_items")
    op.drop_index("ix_skin_items_category_sell", table_name="skin_items")
    op.drop_column("skin_items", "discount_percent")
    op.drop_column("skin_items", "sell_price_usd")
