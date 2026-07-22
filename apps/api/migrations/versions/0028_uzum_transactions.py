"""Uzum transactions: the source of truth for Uzum Bank's Merchant API state machine.

``uzum_transactions`` is keyed on ``trans_id`` (Uzum's own transaction id) so
``/create``/``/confirm``/``/reverse`` are idempotent against replays. Unlike
Payme's integer ``state``, ``status`` is our own string machine: ``CREATED``,
``CONFIRMED``, ``REVERSED``, ``FAILED``. This is the inverted-webhook twin of
``payme_transactions`` (migration ``0027``).

Revision ID: 0028_uzum_transactions
Revises: 0027_payme_transactions
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_uzum_transactions"
down_revision: str | None = "0027_payme_transactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uzum_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("trans_id", sa.String(64), nullable=False),
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
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("service_id", sa.BigInteger, nullable=True),
        sa.Column("create_time", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("confirm_time", sa.BigInteger, nullable=True),
        sa.Column("reverse_time", sa.BigInteger, nullable=True),
        sa.Column(
            "payment_source",
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
        sa.UniqueConstraint("trans_id", name="uq_uzum_transactions_trans_id"),
        sa.CheckConstraint(
            "status IN ('CREATED', 'CONFIRMED', 'REVERSED', 'FAILED')",
            name="ck_uzum_transactions_status",
        ),
    )
    op.create_index("ix_uzum_transactions_order", "uzum_transactions", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_uzum_transactions_order", table_name="uzum_transactions")
    op.drop_table("uzum_transactions")
