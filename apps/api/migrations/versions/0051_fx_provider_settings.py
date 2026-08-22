"""Admin-ordered FX provider chain.

Revision ID: 0051_fx_provider_settings
Revises: 0050_fx_quote_settings
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051_fx_provider_settings"
down_revision: str | None = "0050_fx_quote_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT: tuple[tuple[str, int], ...] = (
    ("fxratesapi", 0),
    ("exchangerate-api", 1),
    ("exchangerate-host", 2),
    ("openexchangerates", 3),
    ("coingecko", 4),
)


def upgrade() -> None:
    op.create_table(
        "fx_provider_settings",
        sa.Column("slug", sa.String(32), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.bulk_insert(
        sa.table(
            "fx_provider_settings",
            sa.column("slug", sa.String(32)),
            sa.column("sort_order", sa.Integer()),
        ),
        [{"slug": slug, "sort_order": order} for slug, order in _DEFAULT],
    )


def downgrade() -> None:
    op.drop_table("fx_provider_settings")
