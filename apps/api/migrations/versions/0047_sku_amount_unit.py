"""Let a variable-amount SKU be priced in something other than dollars.

Revision ID: 0047_sku_amount_unit
Revises: 0046_order_source
Create Date: 2026-08-18

The variable-amount model was built for the Steam wallet, where the thing the
customer types *is* dollars: ``min_amount_usd`` / ``max_amount_usd`` bound it and
``unit_price_usd`` records it. Telegram Stars is the same shape of purchase — any
amount, priced by a rate — but the customer thinks in stars, not in the $0.01545
each one costs. Asking them for dollars would be asking them to do arithmetic the
page can do.

So the amount grows a unit:

* ``amount_unit`` — what the customer types, for the storefront to label the
  field with. NULL means dollars, which is every existing row.
* ``units_per_usd`` — how many of them a dollar buys (64.705882 for Stars). NULL
  means one, again matching every existing row.

The USD bounds stay authoritative and stay in USD: pricing, revenue and the FX
snapshot all speak dollars, and giving them a second currency to be right about
is how those go wrong. The storefront converts for display, and checkout snaps
the amount to a whole unit before it prices anything — a customer who asked for
500 stars must be charged for 500, not for 499.9997 worth.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0047_sku_amount_unit"
down_revision: str | None = "0046_order_source"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("skus", sa.Column("amount_unit", sa.String(length=32), nullable=True))
    op.add_column("skus", sa.Column("units_per_usd", sa.Numeric(20, 6), nullable=True))
    # A unit without a rate cannot be converted, and a rate without a unit has
    # nothing to label; either alone would render a field the storefront cannot
    # price. Zero or negative would divide by zero or invert the sale.
    op.create_check_constraint(
        "ck_skus_amount_unit_complete",
        "skus",
        "(amount_unit IS NULL AND units_per_usd IS NULL) "
        "OR (amount_unit IS NOT NULL AND units_per_usd IS NOT NULL AND units_per_usd > 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_skus_amount_unit_complete", "skus", type_="check")
    op.drop_column("skus", "units_per_usd")
    op.drop_column("skus", "amount_unit")
