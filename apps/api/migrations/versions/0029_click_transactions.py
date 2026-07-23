"""Click transactions: the source of truth for Click Shop API's Prepare/Complete state machine.

``click_transactions`` is keyed on ``UNIQUE(click_trans_id, service_id)`` so
``/prepare``/``/complete`` are idempotent against replays. ``merchant_prepare_id``
is a DB IDENTITY bigint — Click's Prepare response requires an integer id, unlike
our usual UUID string ids. ``status`` is our own string machine: ``PREPARED``,
``CONFIRMED``, ``CANCELLED``. This is the inverted-webhook twin of
``uzum_transactions`` (migration ``0028``).

Revision ID: 0029_click_transactions
Revises: 0028_uzum_transactions
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_click_transactions"
down_revision: str | None = "0028_uzum_transactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "click_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "merchant_prepare_id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
            unique=True,
        ),
        sa.Column("click_trans_id", sa.BigInteger, nullable=False),
        sa.Column("service_id", sa.BigInteger, nullable=False),
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
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("click_paydoc_id", sa.BigInteger, nullable=True),
        sa.Column("prepare_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("complete_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_time", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "click_trans_id", "service_id", name="uq_click_transactions_trans_service"
        ),
        sa.CheckConstraint(
            "status IN ('PREPARED', 'CONFIRMED', 'CANCELLED')",
            name="ck_click_transactions_status",
        ),
    )
    op.create_index("ix_click_transactions_order", "click_transactions", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_click_transactions_order", table_name="click_transactions")
    op.drop_table("click_transactions")
