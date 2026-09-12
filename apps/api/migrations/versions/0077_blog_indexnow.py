"""IndexNow outbox for blog publish / archive.

Revision ID: 0077_blog_indexnow
Revises: 0076_blog_engagement
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0077_blog_indexnow"
down_revision: str | None = "0076_blog_engagement"
branch_labels: str | None = None
depends_on: str | None = None

_TS = sa.DateTime(timezone=True)
_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "blog_indexnow_pings",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("blog_posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("urls", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("finished_at", _TS, nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("reason IN ('published', 'archived')", name="reason_known"),
        sa.CheckConstraint(
            "status IN ('pending', 'done', 'skipped', 'failed')",
            name="status_known",
        ),
    )
    op.create_index(
        "ix_blog_indexnow_pings_pending",
        "blog_indexnow_pings",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_blog_indexnow_pings_pending", table_name="blog_indexnow_pings")
    op.drop_table("blog_indexnow_pings")
