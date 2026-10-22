"""``push_devices`` and ``push_messages``: pushes to the mobile app through Expo (ADR-0102).

A device is one install's Expo push token, owned by the account signed in on it. A message is
one push to one device, queued in the transaction that changed the order and sent by the
worker (channel ``push_queue``). ``(device_id, dedupe_key)`` is unique so one outcome pushes
once per device. The two partial indexes serve the worker's claim and the receipts job.

Revision ID: 0105_push_notifications
Revises: 0104_payment_review_limits
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0105_push_notifications"
down_revision: str | None = "0104_payment_review_limits"
branch_labels: str | None = None
depends_on: str | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "push_devices",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_push_devices_user_id_users"),
            nullable=False,
        ),
        sa.Column("token", sa.String(200), nullable=False),
        sa.Column("platform", sa.String(8), nullable=False),
        sa.Column("app_version", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_reason", sa.String(32), nullable=True),
        sa.UniqueConstraint("token", name="uq_push_devices_token"),
        sa.CheckConstraint("platform IN ('ios', 'android')", name="ck_push_devices_platform_known"),
    )
    op.create_index(
        "ix_push_devices_user_active",
        "push_devices",
        ["user_id"],
        postgresql_where=sa.text("disabled_at IS NULL"),
    )
    op.create_table(
        "push_messages",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "device_id",
            UUID(as_uuid=False),
            sa.ForeignKey(
                "push_devices.id",
                ondelete="CASCADE",
                name="fk_push_messages_device_id_push_devices",
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_push_messages_user_id_users"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("dedupe_key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.String(240), nullable=False),
        sa.Column("data", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW
        ),
        sa.Column("ticket_id", sa.String(64), nullable=True),
        sa.Column("receipt_status", sa.String(16), nullable=True),
        sa.Column("receipt_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "device_id", "dedupe_key", name="uq_push_messages_device_id_dedupe_key"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped')",
            name="ck_push_messages_status_known",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_push_messages_attempts_nonneg"),
    )
    op.create_index(
        "ix_push_messages_pending",
        "push_messages",
        ["next_attempt_at", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_push_messages_receipt_due",
        "push_messages",
        ["sent_at"],
        postgresql_where=sa.text("status = 'sent' AND receipt_checked_at IS NULL"),
    )
    op.create_index("ix_push_messages_user_id", "push_messages", ["user_id"])


def downgrade() -> None:
    op.drop_table("push_messages")
    op.drop_table("push_devices")
