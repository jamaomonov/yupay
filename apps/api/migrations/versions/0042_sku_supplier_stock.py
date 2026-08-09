"""Supplier stock per SKU, for voucher inventory held at G2B.

Game top-ups are generated on demand and never run out. Gift cards and vouchers
are real codes sitting in a supplier's warehouse, and G2B reports how many are
left per product — including plenty of zeroes. Selling one we cannot deliver
turns into a manual refund, so the count is stored and checked before checkout.

Nullable on purpose, and that is the meaning rather than an oversight:

    NULL   not tracked — every game top-up, and voucher lines G2B reports as
           unlimited (it answers ``-1`` for those, normalised to NULL on write)
    0      out of stock — do not sell
    > 0    that many codes left at the supplier

The count itself is deliberately not exposed to customers; the storefront only
learns the boolean ``Sku.in_stock`` derived from it. Showing "3 left" invites a
rush on a number we do not control and cannot honour once another reseller
drains it.

Revision ID: 0042_sku_supplier_stock
Revises: 0041_user_ban
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0042_sku_supplier_stock"
down_revision: str | None = "0041_user_ban"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("skus", sa.Column("supplier_stock", sa.Integer(), nullable=True))
    op.add_column(
        "skus",
        sa.Column("supplier_stock_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_skus_supplier_stock_non_negative",
        "skus",
        "supplier_stock IS NULL OR supplier_stock >= 0",
    )
    # The storefront's hot path is "sellable SKUs of this product", and after
    # this change that means `active AND (supplier_stock IS NULL OR > 0)`.
    # Partial index on the rows that are actually out of stock: they are the
    # minority, and it is the set the admin wants to list.
    op.create_index(
        "ix_skus_out_of_stock",
        "skus",
        ["product_id"],
        unique=False,
        postgresql_where=sa.text("supplier_stock = 0"),
    )


def downgrade() -> None:
    op.drop_index("ix_skus_out_of_stock", table_name="skus")
    op.drop_constraint("ck_skus_supplier_stock_non_negative", "skus", type_="check")
    op.drop_column("skus", "supplier_stock_at")
    op.drop_column("skus", "supplier_stock")
