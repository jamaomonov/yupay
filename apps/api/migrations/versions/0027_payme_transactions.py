"""Payme transactions: the source of truth for Payme's Merchant API state machine.

``payme_transactions`` is keyed on ``payme_id`` (Payme's own transaction id) so
``CreateTransaction``/``PerformTransaction``/``CancelTransaction`` are idempotent
against replays. ``state`` follows Payme's own encoding: ``1`` created, ``2``
performed, ``-1`` cancelled before perform, ``-2`` cancelled after perform.

Revision ID: 0027_payme_transactions
Revises: 0026_broadcasts
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_payme_transactions"
down_revision: str | None = "0026_broadcasts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payme_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("payme_id", sa.String(64), nullable=False),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payment_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("payments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("amount_tiyin", sa.BigInteger, nullable=False),
        sa.Column("state", sa.Integer, nullable=False),
        sa.Column("reason", sa.Integer, nullable=True),
        sa.Column("create_time", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("perform_time", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("cancel_time", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "fiscal_data",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("payme_id", name="uq_payme_transactions_payme_id"),
        sa.CheckConstraint("state IN (1, 2, -1, -2)", name="ck_payme_transactions_state"),
    )
    op.create_index("ix_payme_transactions_order", "payme_transactions", ["order_id"])
    op.create_index(
        "ix_payme_transactions_state_create",
        "payme_transactions",
        ["state", "create_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_payme_transactions_state_create", table_name="payme_transactions")
    op.drop_index("ix_payme_transactions_order", table_name="payme_transactions")
    op.drop_table("payme_transactions")
