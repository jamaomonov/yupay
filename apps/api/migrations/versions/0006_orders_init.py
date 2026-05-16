"""Orders: aggregate, items, and audit events. See ADR-0011.

Revision ID: 0006_orders_init
Revises: 0005_users_roles
Create Date: 2026-05-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_orders_init"
down_revision: str | None = "0005_users_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ORDER_STATUSES = (
    "pending_payment",
    "paid",
    "fulfilling",
    "fulfilled",
    "delivered",
    "failed",
    "cancelled",
    "expired",
    "refunded",
    "partially_refunded",
)


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("guest_email", postgresql.CITEXT(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("total_usd", sa.Numeric(20, 6), nullable=False),
        sa.Column("total_charged", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "fx_snapshot_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("fx_snapshots.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("ip_hash", sa.CHAR(64), nullable=True),
        sa.Column("ua_hash", sa.CHAR(64), nullable=True),
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
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ("
            + ", ".join(f"'{s}'" for s in _ORDER_STATUSES)
            + ")",
            name="ck_orders_status",
        ),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (guest_email IS NULL)",
            name="ck_orders_actor_exclusive",
        ),
        sa.CheckConstraint("total_usd >= 0", name="ck_orders_total_usd_nonneg"),
        sa.CheckConstraint("total_charged >= 0", name="ck_orders_total_charged_nonneg"),
    )
    op.create_index(
        "ix_orders_user_created",
        "orders",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_orders_guest_email_created",
        "orders",
        ["guest_email", sa.text("created_at DESC")],
        postgresql_where=sa.text("guest_email IS NOT NULL"),
    )
    op.create_index(
        "ix_orders_status_pending_expires",
        "orders",
        ["expires_at"],
        postgresql_where=sa.text("status = 'pending_payment'"),
    )
    # Per-actor idempotency. Two partial UNIQUEs because one column is always NULL.
    op.create_index(
        "uq_orders_idem_user",
        "orders",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text(
            "user_id IS NOT NULL AND idempotency_key IS NOT NULL"
        ),
    )
    op.create_index(
        "uq_orders_idem_guest",
        "orders",
        ["guest_email", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text(
            "guest_email IS NOT NULL AND idempotency_key IS NOT NULL"
        ),
    )

    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sku_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("skus.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("unit_price_usd", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "fulfillment_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "fulfillment_state",
            sa.String(24),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("supplier_order_id", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("qty > 0", name="ck_order_items_qty_positive"),
        sa.CheckConstraint("unit_price_usd > 0", name="ck_order_items_price_positive"),
        sa.CheckConstraint(
            "fulfillment_state IN ("
            "'pending', 'reserved', 'in_progress', 'delivered', 'failed', 'refunded'"
            ")",
            name="ck_order_items_state",
        ),
    )
    op.create_index("ix_order_items_order", "order_items", ["order_id"])
    op.create_index(
        "ix_order_items_state_active",
        "order_items",
        ["fulfillment_state"],
        postgresql_where=sa.text(
            "fulfillment_state IN ('pending', 'reserved', 'in_progress')"
        ),
    )

    op.create_table(
        "order_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("actor", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_order_events_order_created",
        "order_events",
        ["order_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_order_events_order_created", table_name="order_events")
    op.drop_table("order_events")
    op.drop_index("ix_order_items_state_active", table_name="order_items")
    op.drop_index("ix_order_items_order", table_name="order_items")
    op.drop_table("order_items")
    op.drop_index("uq_orders_idem_guest", table_name="orders")
    op.drop_index("uq_orders_idem_user", table_name="orders")
    op.drop_index("ix_orders_status_pending_expires", table_name="orders")
    op.drop_index("ix_orders_guest_email_created", table_name="orders")
    op.drop_index("ix_orders_user_created", table_name="orders")
    op.drop_table("orders")
