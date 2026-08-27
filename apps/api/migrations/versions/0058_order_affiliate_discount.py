"""Affiliate discount columns on orders and order items.

``order_items.discount_usd`` is the load-bearing one. Revenue and margin are
computed from line-level ``unit_price_usd``/``rate_multiplier`` in
``orders/revenue.py``, not from ``orders.total_charged``, so a discount that
only reduced the payable total would be invisible to every report — the admin
would see full margin on exactly the orders that have the least of it, and
would not find out for weeks.

Distributing the discount down to the lines lets both revenue expressions
subtract it once, keeping ``gross - margin == cost`` true with the discount
taken out of both sides.

NOT NULL DEFAULT 0 rather than nullable: every order written before this
genuinely had no discount, and a zero is easier to sum than a NULL.

Revision ID: 0058_order_affiliate_discount
Revises: 0057_affiliate_program
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0058_order_affiliate_discount"
down_revision: str | None = "0057_affiliate_program"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("affiliate_code_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.create_foreign_key(
        "fk_orders_affiliate_code",
        "orders",
        "affiliate_codes",
        ["affiliate_code_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "orders",
        sa.Column(
            "discount_charged",
            sa.Numeric(20, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "order_items",
        sa.Column("discount_usd", sa.Numeric(20, 6), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("order_items", "discount_usd")
    op.drop_column("orders", "discount_charged")
    op.drop_constraint("fk_orders_affiliate_code", "orders", type_="foreignkey")
    op.drop_column("orders", "affiliate_code_id")
