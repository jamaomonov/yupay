"""Broadcasts: broadcasts, broadcast_recipients, telegram_links.bot_blocked_at.

An admin composes a ``Broadcast`` targeting a cohort of Telegram-linked users; the
dispatch job (a later task) fans it out into one ``broadcast_recipients`` row per
target. ``telegram_links.bot_blocked_at`` lets that job skip recipients already known
to have blocked the bot without a live send attempt.

Revision ID: 0026_broadcasts
Revises: 0025_variable_amount_skus
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_broadcasts"
down_revision: str | None = "0025_variable_amount_skus"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_BROADCAST_STATUSES = ("draft", "scheduled", "sending", "sent", "failed", "canceled")
_MEDIA_TYPES = ("none", "photo", "video", "animation", "document")
_RECIPIENT_STATUSES = ("pending", "sent", "failed", "blocked")


def upgrade() -> None:
    op.create_table(
        "broadcasts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("body_html", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("media_type", sa.String(16), nullable=False, server_default=sa.text("'none'")),
        sa.Column("media_url", sa.Text, nullable=True),
        sa.Column("media_file_id", sa.Text, nullable=True),
        sa.Column("locale_filter", sa.String(8), nullable=True),
        sa.Column(
            "disable_web_page_preview",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_recipients", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("sent_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("blocked_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id"),
            nullable=False,
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
        sa.CheckConstraint(
            "status IN " + repr(_BROADCAST_STATUSES),
            name="ck_broadcasts_status",
        ),
        sa.CheckConstraint(
            "media_type IN " + repr(_MEDIA_TYPES),
            name="ck_broadcasts_media_type",
        ),
    )

    op.create_table(
        "broadcast_recipients",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "broadcast_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("broadcasts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("tg_chat_id", sa.BigInteger, nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "broadcast_id", "user_id", name="uq_broadcast_recipients_broadcast_user"
        ),
        sa.CheckConstraint(
            "status IN " + repr(_RECIPIENT_STATUSES),
            name="ck_broadcast_recipients_status",
        ),
    )
    op.create_index(
        "ix_broadcast_recipients_broadcast_status",
        "broadcast_recipients",
        ["broadcast_id", "status"],
    )

    op.add_column(
        "telegram_links",
        sa.Column("bot_blocked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegram_links", "bot_blocked_at")
    op.drop_index("ix_broadcast_recipients_broadcast_status", table_name="broadcast_recipients")
    op.drop_table("broadcast_recipients")
    op.drop_table("broadcasts")
