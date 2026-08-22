"""Mark catalog vs wallet-funding orders.

Revision ID: 0052_order_purpose
Revises: 0051_fx_provider_settings
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052_order_purpose"
down_revision: str | None = "0051_fx_provider_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "purpose",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'catalog'"),
        ),
    )
    op.create_check_constraint(
        "ck_orders_purpose_known",
        "orders",
        "purpose IN ('catalog', 'wallet_topup')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_purpose_known", "orders", type_="check")
    op.drop_column("orders", "purpose")
