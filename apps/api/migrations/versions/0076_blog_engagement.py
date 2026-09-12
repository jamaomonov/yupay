"""Anonymous blog likes and unique views (cookie, not IP).

Revision ID: 0076_blog_engagement
Revises: 0075_blog
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0076_blog_engagement"
down_revision: str | None = "0075_blog"
branch_labels: str | None = None
depends_on: str | None = None

_TS = sa.DateTime(timezone=True)
_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.add_column(
        "blog_posts",
        sa.Column("like_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "blog_posts",
        sa.Column("view_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_table(
        "blog_post_likes",
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("blog_posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reader_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.PrimaryKeyConstraint("post_id", "reader_hash", name="pk_blog_post_likes"),
    )
    op.create_table(
        "blog_post_views",
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("blog_posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reader_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.PrimaryKeyConstraint("post_id", "reader_hash", name="pk_blog_post_views"),
    )


def downgrade() -> None:
    op.drop_table("blog_post_views")
    op.drop_table("blog_post_likes")
    op.drop_column("blog_posts", "view_count")
    op.drop_column("blog_posts", "like_count")
