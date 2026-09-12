"""Editorial blog: posts bound to a catalogue brand.

Four tables, no changes to existing ones. Public routes and sanitize land
in later tasks of this feature so the schema can ship on its own. See
``docs/superpowers/specs/2026-09-12-blog-design.md`` §7.

Revision ID: 0075_blog
Revises: 0074_admin_wallet_order_search
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0075_blog"
down_revision: str | None = "0074_admin_wallet_order_search"
branch_labels: str | None = None
depends_on: str | None = None

_TS = sa.DateTime(timezone=True)
_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "blog_posts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "primary_brand_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("brands.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "show_buy_card",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "pin_on_brand",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("cover_image_url", sa.String(length=512), nullable=True),
        sa.Column("event_starts_at", _TS, nullable=True),
        sa.Column("event_ends_at", _TS, nullable=True),
        sa.Column("published_at", _TS, nullable=True),
        sa.Column("scheduled_for", _TS, nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.CheckConstraint(
            "kind IN ('guide', 'news', 'update', 'event')",
            name="kind_known",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'scheduled', 'published', 'archived')",
            name="status_known",
        ),
    )
    op.create_index(
        "ix_blog_posts_status_published",
        "blog_posts",
        ["status", "published_at"],
    )
    op.create_index(
        "ix_blog_posts_brand_status_published",
        "blog_posts",
        ["primary_brand_id", "status", "published_at"],
    )
    op.create_index(
        "ix_blog_posts_brand_pinned",
        "blog_posts",
        ["primary_brand_id"],
        postgresql_where=sa.text("pin_on_brand AND status = 'published'"),
    )

    op.create_table(
        "blog_post_translations",
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("blog_posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(length=3), nullable=False),
        sa.Column("slug", sa.String(length=96), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "excerpt",
            sa.String(length=280),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column("body_html", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("seo_title", sa.String(length=200), nullable=True),
        sa.Column("seo_description", sa.String(length=320), nullable=True),
        sa.PrimaryKeyConstraint("post_id", "locale", name="pk_blog_post_translations"),
        sa.CheckConstraint("locale IN ('ru', 'en', 'uz')", name="locale_known"),
        sa.UniqueConstraint("locale", "slug", name="uq_blog_post_translations_locale_slug"),
    )

    op.create_table(
        "blog_post_brands",
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("blog_posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "brand_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("brands.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("post_id", "brand_id", name="pk_blog_post_brands"),
    )

    op.create_table(
        "blog_post_faqs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("blog_posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(length=3), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("question", sa.String(length=280), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.CheckConstraint("locale IN ('ru', 'en', 'uz')", name="locale_known"),
        sa.UniqueConstraint(
            "post_id",
            "locale",
            "sort_order",
            name="uq_blog_post_faqs_post_locale_sort",
        ),
    )
    op.create_index(
        "ix_blog_post_faqs_post_locale",
        "blog_post_faqs",
        ["post_id", "locale"],
    )


def downgrade() -> None:
    op.drop_table("blog_post_faqs")
    op.drop_table("blog_post_brands")
    op.drop_table("blog_post_translations")
    op.drop_index("ix_blog_posts_brand_pinned", table_name="blog_posts")
    op.drop_index("ix_blog_posts_brand_status_published", table_name="blog_posts")
    op.drop_index("ix_blog_posts_status_published", table_name="blog_posts")
    op.drop_table("blog_posts")
