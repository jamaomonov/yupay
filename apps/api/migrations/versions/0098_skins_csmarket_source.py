"""Skins bought through csmarket (ADR-0098): source ids on items, supplier on trades.

Revision ID: 0098_skins_csmarket_source
Revises: 0097_p2p_reservation_order
Create Date: 2026-10-09

* ``skin_items.source_item_id`` — csmarket's item id, written by the feed sync; the key
  the live-offer read and the purchase use. NULL under the Waxpeer source.
* ``skin_trades.supplier`` — who the trade was bought from. Every existing row is a
  Waxpeer trade, hence the server default; an order keeps its supplier when the source
  switch flips, so the status sweep asks the right one.
* ``skin_trades.offer_id`` / ``supplier_order_id`` — csmarket's opaque offer id and its
  order number. ``listing_id`` stays the numeric id the storefront speaks (for csmarket a
  stable 52-bit hash of ``offer_id``).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0098_skins_csmarket_source"
down_revision: str | None = "0097_p2p_reservation_order"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("skin_items", sa.Column("source_item_id", sa.String(64), nullable=True))
    op.add_column(
        "skin_trades",
        sa.Column("supplier", sa.String(16), nullable=False, server_default=sa.text("'waxpeer'")),
    )
    op.add_column("skin_trades", sa.Column("offer_id", sa.Text(), nullable=True))
    op.add_column("skin_trades", sa.Column("supplier_order_id", sa.String(32), nullable=True))
    op.create_check_constraint(
        "ck_skin_trades_supplier", "skin_trades", "supplier IN ('waxpeer', 'csmarket')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_skin_trades_supplier", "skin_trades", type_="check")
    op.drop_column("skin_trades", "supplier_order_id")
    op.drop_column("skin_trades", "offer_id")
    op.drop_column("skin_trades", "supplier")
    op.drop_column("skin_items", "source_item_id")
