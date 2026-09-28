"""skin_trades: index for the admin trades screen (newest first).

Revision ID: 0090_skin_trades_created_idx
Revises: 0089_skins_purchase
"""

from __future__ import annotations

from alembic import op

revision: str = "0090_skin_trades_created_idx"
down_revision: str | None = "0089_skins_purchase"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index("ix_skin_trades_created_at", "skin_trades", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_skin_trades_created_at", table_name="skin_trades")
