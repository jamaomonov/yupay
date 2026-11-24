"""``skus.one_time_pack``: a pack the game sells once per account (ADR-0108).

Revision ID: 0113_sku_one_time_pack
Revises: 0112_uzqr_provider
Create Date: 2026-11-24

Free Fire's Level Up Packages: a player who already bought one, or is past its
level, is refused by every supplier — 42 % of «Level Up Package 6» orders came
back refunded over sixty days. A flagged SKU is sold to signed-in customers
only, its supplier refusal refunds to the buyer's balance at once, and it is
never handed to another supplier.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0113_sku_one_time_pack"
down_revision: str | None = "0112_uzqr_provider"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "skus",
        sa.Column("one_time_pack", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("skus", "one_time_pack")
