"""Pin the rate an order line was priced at (ADR-0051).

A variable-amount line's margin lives in the rate it was quoted at, not in a
fee column, so its value in USD is ``unit_price_usd * rate_multiplier``. That
multiplier was only ever read from the live ``skus`` row, which an admin can
change — so editing the Steam margin silently revalued every order ever taken.

``rate_multiplier`` records the markup actually applied to the line and
``fx_rate`` the guarded market rate it was priced against, both written once at
checkout. Nullable, and the null carries meaning: an override-priced line never
touched a rate, and a fixed-price line has no multiplier.

Deliberately **not** backfilled. Filling old rows from today's
``skus.rate_multiplier`` would reproduce the numbers the query-side fallback
already produces while making a guess indistinguishable from a recorded fact.
NULL means "not recorded, fall back to the SKU" — see
``orders.revenue.charged_usd_expr``.

Revision ID: 0044_order_item_rate_snapshot
Revises: 0043_sku_margin_percent
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0044_order_item_rate_snapshot"
down_revision: str | None = "0043_sku_margin_percent"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Same precision as the columns these mirror: skus.rate_multiplier is
    # NUMERIC(10, 4) and fx_snapshots.rate is NUMERIC(20, 10).
    op.add_column("order_items", sa.Column("rate_multiplier", sa.Numeric(10, 4), nullable=True))
    op.add_column("order_items", sa.Column("fx_rate", sa.Numeric(20, 10), nullable=True))
    # A recorded rate is a positive number or it is not recorded at all; a zero
    # or negative one would silently zero out an order's value in every report.
    op.create_check_constraint(
        "ck_order_items_rate_multiplier_positive",
        "order_items",
        "rate_multiplier IS NULL OR rate_multiplier > 0",
    )
    op.create_check_constraint(
        "ck_order_items_fx_rate_positive",
        "order_items",
        "fx_rate IS NULL OR fx_rate > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_order_items_fx_rate_positive", "order_items", type_="check")
    op.drop_constraint("ck_order_items_rate_multiplier_positive", "order_items", type_="check")
    op.drop_column("order_items", "fx_rate")
    op.drop_column("order_items", "rate_multiplier")
