"""brands.visible_retail — hide a brand from the storefront, keep it for resellers.

Revision ID: 0094_brand_visible_retail
Revises: 0093_p2p_deposit
Create Date: 2026-10-04

``active`` stays the master switch for both channels; ``visible_retail`` is the
storefront's gate beside ``visible_b2b``. Defaults to true, so every existing
brand keeps its current retail visibility. ADR-0095.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0094_brand_visible_retail"
down_revision: str | None = "0093_p2p_deposit"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "brands",
        sa.Column("visible_retail", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("brands", "visible_retail")
