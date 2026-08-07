"""Chargeback evidence capture per order (ADR-0044).

One row per order, holding the request context an acquirer asks for when a
cardholder disputes a payment: the address the order came from, the browser
that sent it, and whatever passive hints that browser volunteered.

This is the only table in the schema with an unhashed IP. ``purge_after`` is
stamped per row at capture time rather than derived from config at delete time,
so shortening the retention policy later cannot silently extend the life of
data already collected under an earlier promise.

``ix_order_evidence_purge_after`` exists for the purge job's only query. Without
it the sweep degrades into a full scan of a table that grows with every order.

Revision ID: 0040_order_evidence
Revises: 0039_orders_admin_search_indexes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_order_evidence"
down_revision: str | None = "0039_orders_admin_search_indexes"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "order_evidence",
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("accept_language", sa.String(length=128), nullable=True),
        sa.Column(
            "client_hints",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_order_evidence_purge_after", "order_evidence", ["purge_after"])


def downgrade() -> None:
    op.drop_index("ix_order_evidence_purge_after", table_name="order_evidence")
    op.drop_table("order_evidence")
