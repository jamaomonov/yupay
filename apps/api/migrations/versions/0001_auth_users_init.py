"""Initial: users, telegram_links, auth_sessions.

Revision ID: 0001_auth_users_init
Revises:
Create Date: 2026-05-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_auth_users_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("locale", sa.String(8), nullable=False, server_default="ru"),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("photo_url", sa.String(1024), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_users_email_alive",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index("ix_users_created_at", "users", ["created_at"])

    op.create_table(
        "telegram_links",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("tg_username", sa.String(64), nullable=True),
        sa.Column("first_name", sa.String(255), nullable=True),
        sa.Column("last_name", sa.String(255), nullable=True),
        sa.Column("language_code", sa.String(8), nullable=True),
        sa.Column("is_premium", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_telegram_links_user_id", "telegram_links", ["user_id"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        # SHA-256 hex digest of the refresh token (null for guest sessions).
        sa.Column("refresh_token_hash", sa.CHAR(64), nullable=True),
        sa.Column("guest_email", postgresql.CITEXT(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("ip_hash", sa.CHAR(64), nullable=True),
        sa.Column("ua_hash", sa.CHAR(64), nullable=True),
        sa.CheckConstraint(
            "kind IN ('user', 'guest')",
            name="ck_auth_sessions_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'user' AND user_id IS NOT NULL AND refresh_token_hash IS NOT NULL) "
            "OR (kind = 'guest' AND user_id IS NULL AND guest_email IS NOT NULL)",
            name="ck_auth_sessions_shape",
        ),
    )
    op.create_index(
        "uq_auth_sessions_refresh_hash",
        "auth_sessions",
        ["refresh_token_hash"],
        unique=True,
        postgresql_where=sa.text("refresh_token_hash IS NOT NULL"),
    )
    op.create_index(
        "ix_auth_sessions_user_alive",
        "auth_sessions",
        ["user_id", "expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_auth_sessions_guest_email",
        "auth_sessions",
        ["guest_email"],
        postgresql_where=sa.text("guest_email IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_guest_email", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_alive", table_name="auth_sessions")
    op.drop_index("uq_auth_sessions_refresh_hash", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_index("ix_telegram_links_user_id", table_name="telegram_links")
    op.drop_table("telegram_links")

    op.drop_index("ix_users_created_at", table_name="users")
    op.drop_index("uq_users_email_alive", table_name="users")
    op.drop_table("users")
