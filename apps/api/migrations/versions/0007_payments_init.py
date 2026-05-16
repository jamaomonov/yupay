"""Payments skeleton: payments, payment_attempts, payment_webhooks. See ADR-0012.

Revision ID: 0007_payments_init
Revises: 0006_orders_init
Create Date: 2026-05-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_payments_init"
down_revision: str | None = "0006_orders_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PAYMENT_STATUSES = (
    "pending",
    "requires_action",
    "succeeded",
    "failed",
    "cancelled",
    "refunded",
    "partially_refunded",
)


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("intent_url", sa.String(2048), nullable=True),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
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
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _PAYMENT_STATUSES) + ")",
            name="ck_payments_status",
        ),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
    )
    op.create_index("ix_payments_order", "payments", ["order_id"])
    op.create_index(
        "ix_payments_pending",
        "payments",
        ["order_id"],
        postgresql_where=sa.text("status IN ('pending', 'requires_action')"),
    )
    op.create_index(
        "uq_payments_provider_external",
        "payments",
        ["provider", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    op.create_table(
        "payment_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "payment_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("payments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "kind IN ('create_intent', 'webhook', 'refund', 'cancel', 'status_check')",
            name="ck_payment_attempts_kind",
        ),
        sa.CheckConstraint("status IN ('ok', 'error')", name="ck_payment_attempts_status"),
    )
    op.create_index(
        "ix_payment_attempts_payment",
        "payment_attempts",
        ["payment_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "payment_webhooks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("external_event_id", sa.String(255), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("signature_ok", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "uq_payment_webhooks_provider_event",
        "payment_webhooks",
        ["provider", "external_event_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_payment_webhooks_provider_event", table_name="payment_webhooks")
    op.drop_table("payment_webhooks")
    op.drop_index("ix_payment_attempts_payment", table_name="payment_attempts")
    op.drop_table("payment_attempts")
    op.drop_index("uq_payments_provider_external", table_name="payments")
    op.drop_index("ix_payments_pending", table_name="payments")
    op.drop_index("ix_payments_order", table_name="payments")
    op.drop_table("payments")
