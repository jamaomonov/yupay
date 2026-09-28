"""skin_trades: admin screen index, the audit's last verdict, an operator's "resolved".

Revision ID: 0090_skin_trades_created_idx
Revises: 0089_skins_purchase
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0090_skin_trades_created_idx"
down_revision: str | None = "0089_skins_purchase"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index("ix_skin_trades_created_at", "skin_trades", ["created_at"])
    op.add_column("skin_trades", sa.Column("audit_verdict", sa.String(32), nullable=True))
    op.add_column(
        "skin_trades", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("skin_trades", sa.Column("resolved_by", sa.String(64), nullable=True))
    op.add_column("skin_trades", sa.Column("resolved_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("skin_trades", "resolved_note")
    op.drop_column("skin_trades", "resolved_by")
    op.drop_column("skin_trades", "resolved_at")
    op.drop_column("skin_trades", "audit_verdict")
    op.drop_index("ix_skin_trades_created_at", table_name="skin_trades")
