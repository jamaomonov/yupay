"""Record how many units a package SKU delivers, so a free amount can be priced from it.

Revision ID: 0048_sku_units
Revises: 0047_sku_amount_unit
Create Date: 2026-08-18

Margin is about to stop being one number. The intent is 20% on the small
Telegram Stars packs and less on the large ones — the ordinary volume discount —
which means there is no longer a single rate that prices "any amount".

Left alone, the free-amount line would keep pricing off its own multiplier and
drift away from the packages exactly where the discount is deepest: a customer
typing 2500 would be charged the 20% price while the 2500 pack sold at 10%.

So a package says how many units it delivers, and the free amount is priced
*from* whichever package it falls in — 50–74 stars at the 50-pack's per-star
price, 75–99 at the 75-pack's, and so on. The two can then never disagree,
whatever margins are set, because one is derived from the other.

``units`` is NULL for everything that exists today: fixed SKUs that are not sold
by unit, and the variable line itself, whose amount is typed rather than fixed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0048_sku_units"
down_revision: str | None = "0047_sku_amount_unit"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("skus", sa.Column("units", sa.Integer(), nullable=True))
    # Zero would price at infinity per unit; negative is meaningless. NULL is
    # the "not sold by unit" case and stays allowed.
    op.create_check_constraint("ck_skus_units_positive", "skus", "units IS NULL OR units > 0")


def downgrade() -> None:
    op.drop_constraint("ck_skus_units_positive", "skus", type_="check")
    op.drop_column("skus", "units")
