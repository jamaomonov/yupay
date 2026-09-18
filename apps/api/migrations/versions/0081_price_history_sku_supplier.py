"""Index the brand-overview screen's latest-row-per-(sku, supplier) query.

``ix_supplier_price_history_sku_time`` is ``(sku_id, captured_at)`` — built
(0017) for "the last N price points for one SKU, across every supplier,
ordered by time." ``sourcing.brand_overview.get_brand_overview``'s query is a
different shape: ``DISTINCT ON (sku_id, supplier_slug) ... ORDER BY sku_id,
supplier_slug, captured_at DESC`` wants the latest row *per supplier*, and the
old index can find a SKU's rows but not walk them pre-grouped and pre-ordered
by supplier — Postgres still sorts. This index matches the query's
``DISTINCT ON``/``ORDER BY`` column-for-column.

Plain ``CREATE INDEX`` rather than ``CONCURRENTLY``, following 0039/0055:
Alembic runs inside a transaction where ``CONCURRENTLY`` is not allowed, and
at present sizes the lock is momentary.

Revision ID: 0081_price_history_sku_supplier
Revises: 0080_paynet
"""

from __future__ import annotations

from alembic import op

revision: str = "0081_price_history_sku_supplier"
down_revision: str | None = "0080_paynet"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_supplier_price_history_sku_supplier_time "
        "ON supplier_price_history (sku_id, supplier_slug, captured_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_supplier_price_history_sku_supplier_time")
