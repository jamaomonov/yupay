"""supplier_catalog_cache: parent_external_id + price_usdt for game_denom rows.

Lets a ``game_denom`` row point back at its game (``parent_external_id``) and
carry the supplier's own price for that denomination (``price_usdt``) — both
needed so the admin mapping wizard can browse "pick a game, then pick a
denomination" against the cache instead of an operator typing NOVA's
``offer_id`` or G-Engine's ``denomination_id`` in by hand. See
``integrations/catalog_sync.py`` and ADR-0019.

Revision ID: 0082_catalog_cache_denoms
Revises: 0081_price_history_sku_supplier
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0082_catalog_cache_denoms"
down_revision: str | None = "0081_price_history_sku_supplier"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "supplier_catalog_cache",
        sa.Column("parent_external_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "supplier_catalog_cache",
        sa.Column("price_usdt", sa.Numeric(20, 6), nullable=True),
    )
    op.create_index(
        "ix_supplier_catalog_cache_parent",
        "supplier_catalog_cache",
        ["supplier_slug", "kind", "parent_external_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_supplier_catalog_cache_parent", table_name="supplier_catalog_cache")
    op.drop_column("supplier_catalog_cache", "price_usdt")
    op.drop_column("supplier_catalog_cache", "parent_external_id")
