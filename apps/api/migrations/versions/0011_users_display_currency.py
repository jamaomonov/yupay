"""users: add display_currency preference

Stores the customer's preferred display currency (USD / UZS / RUB / USDT) so
clients no longer have to keep it in localStorage. Defaults to ``USD`` for
existing rows.

Revision ID: 0011_users_display_currency
Revises: 0010_inventory_sourcing_init
Create Date: 2026-05-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_users_display_currency"
down_revision: str | None = "0010_inventory_sourcing_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "display_currency",
            sa.String(length=8),
            nullable=False,
            server_default="USD",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "display_currency")
