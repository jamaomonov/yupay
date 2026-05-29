"""Add ``brands.maintenance`` for a soft "temporarily unavailable" state.

``active=False`` hides a brand entirely. Operators also need a softer state:
the brand stays listed but the storefront greys it out, shows a maintenance
badge and blocks purchases (e.g. while a supplier is down). That is what this
boolean drives. Defaults to ``false`` so existing brands keep selling.

Revision ID: 0019_brand_maintenance
Revises: 0018_house_payments_received
Create Date: 2026-05-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_brand_maintenance"
down_revision: str | None = "0018_house_payments_received"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "brands",
        sa.Column(
            "maintenance",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("brands", "maintenance")
