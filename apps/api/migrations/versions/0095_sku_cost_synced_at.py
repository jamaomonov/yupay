"""skus.cost_synced_at — when ``cost_usdt`` was last written by someone who knew the price.

Revision ID: 0095_sku_cost_synced_at
Revises: 0094_brand_visible_retail
Create Date: 2026-10-05

The hourly refresh rewrites ``cost_usdt`` from the routed supplier, and until
now nothing recorded *when* it last managed to. A supplier that stops
answering — key expired, catalogue endpoint moved, 429s all hour — leaves the
old cost in place and every price derived from it, silently. This column is
the clock the staleness alert (``integrations.cost_staleness``) reads.

Backfill: the newest ``supplier_price_history`` row for the SKU, which is the
last moment a supplier stated a price for it; SKUs with a cost but no history
(seeded by hand) get ``now()`` so they are not all stale on the first tick.
SKUs without a cost stay NULL — they are unpriced, not stale.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0095_sku_cost_synced_at"
down_revision: str | None = "0094_brand_visible_retail"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("skus", sa.Column("cost_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        """
        UPDATE skus s
           SET cost_synced_at = COALESCE(
                 (SELECT MAX(h.captured_at) FROM supplier_price_history h WHERE h.sku_id = s.id),
                 CURRENT_TIMESTAMP)
         WHERE s.cost_usdt IS NOT NULL
        """
    )
    op.create_index("ix_skus_cost_synced_at", "skus", ["cost_synced_at"])


def downgrade() -> None:
    op.drop_index("ix_skus_cost_synced_at", table_name="skus")
    op.drop_column("skus", "cost_synced_at")
