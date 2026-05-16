"""Fulfilment skeleton: fulfillment_tasks, fulfillment_attempts, deliveries.

See ADR-0013.

Revision ID: 0008_fulfillment_init
Revises: 0007_payments_init
Create Date: 2026-05-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_fulfillment_init"
down_revision: str | None = "0007_payments_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TASK_STATUSES = ("pending", "in_progress", "succeeded", "failed", "cancelled")
_ATTEMPT_KINDS = ("fulfill", "status_check", "cancel")
_ATTEMPT_STATUSES = ("ok", "error")
_DELIVERY_CHANNELS = ("in_app", "email", "telegram")


def upgrade() -> None:
    op.create_table(
        "fulfillment_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_item_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("order_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("supplier", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "attempts_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("external_order_id", sa.String(128), nullable=True),
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
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN " + repr(_TASK_STATUSES),
            name="ck_fulfillment_tasks_status",
        ),
        sa.CheckConstraint(
            "attempts_count >= 0",
            name="ck_fulfillment_tasks_attempts_nonneg",
        ),
        sa.UniqueConstraint("order_item_id", name="uq_fulfillment_tasks_order_item"),
    )
    op.create_index(
        "ix_fulfillment_tasks_order_id",
        "fulfillment_tasks",
        ["order_id"],
    )
    op.create_index(
        "ix_fulfillment_tasks_status",
        "fulfillment_tasks",
        ["status"],
    )
    op.create_index(
        "uq_fulfillment_tasks_supplier_external",
        "fulfillment_tasks",
        ["supplier", "external_order_id"],
        unique=True,
        postgresql_where=sa.text("external_order_id IS NOT NULL"),
    )

    op.create_table(
        "fulfillment_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("fulfillment_tasks.id", ondelete="CASCADE"),
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
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "kind IN " + repr(_ATTEMPT_KINDS),
            name="ck_fulfillment_attempts_kind",
        ),
        sa.CheckConstraint(
            "status IN " + repr(_ATTEMPT_STATUSES),
            name="ck_fulfillment_attempts_status",
        ),
    )
    op.create_index(
        "ix_fulfillment_attempts_task_id",
        "fulfillment_attempts",
        ["task_id", "created_at"],
    )

    op.create_table(
        "deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "order_item_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("order_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("artifact_kind", sa.String(24), nullable=False),
        sa.Column(
            "artifact",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "channel IN " + repr(_DELIVERY_CHANNELS),
            name="ck_deliveries_channel",
        ),
        sa.UniqueConstraint("order_item_id", name="uq_deliveries_order_item"),
    )
    op.create_index(
        "ix_deliveries_order_item_id",
        "deliveries",
        ["order_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_deliveries_order_item_id", table_name="deliveries")
    op.drop_table("deliveries")
    op.drop_index("ix_fulfillment_attempts_task_id", table_name="fulfillment_attempts")
    op.drop_table("fulfillment_attempts")
    op.drop_index(
        "uq_fulfillment_tasks_supplier_external", table_name="fulfillment_tasks"
    )
    op.drop_index("ix_fulfillment_tasks_status", table_name="fulfillment_tasks")
    op.drop_index("ix_fulfillment_tasks_order_id", table_name="fulfillment_tasks")
    op.drop_table("fulfillment_tasks")
