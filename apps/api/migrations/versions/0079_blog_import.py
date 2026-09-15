"""Imported blog drafts: brand optional on a draft, plus the import ledger.

Revision ID: 0079_blog_import
Revises: 0078_merchant_cabinet
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0079_blog_import"
down_revision: str | None = "0078_merchant_cabinet"
branch_labels: str | None = None
depends_on: str | None = None

_TS = sa.DateTime(timezone=True)
_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    # A draft may arrive before anyone has decided what it sells. The CHECK
    # is what keeps the public queries honest: all of them inner-join
    # ``brands`` through this column and all of them filter to ``published``,
    # so a brandless row can never reach a reader.
    op.alter_column(
        "blog_posts", "primary_brand_id", existing_type=postgresql.UUID(), nullable=True
    )
    # Bare suffix, not the full name: the metadata naming convention in
    # ``core/db.py`` re-templates ``ck_%(table_name)s_%(constraint_name)s``
    # even here, so passing "ck_blog_posts_brand_unless_draft" would ship as
    # ``ck_blog_posts_ck_blog_posts_brand_unless_draft`` and stop matching the
    # ORM's own ``CheckConstraint(name="brand_unless_draft")``.
    op.create_check_constraint(
        "brand_unless_draft",
        "blog_posts",
        "primary_brand_id IS NOT NULL OR status = 'draft'",
    )
    op.create_table(
        "blog_imported_posts",
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=160), nullable=False),
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("blog_posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("rendered_hash", sa.String(length=64), nullable=False),
        sa.Column("source_updated_at", _TS, nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("last_seen_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("last_synced_at", _TS, nullable=False, server_default=_NOW),
        sa.PrimaryKeyConstraint("source", "external_id", name="pk_blog_imported_posts"),
        sa.UniqueConstraint("post_id", name="uq_blog_imported_posts_post"),
        sa.CheckConstraint("source IN ('bunzy')", name="source_known"),
    )


def downgrade() -> None:
    op.drop_table("blog_imported_posts")
    # Down needs a brand on every row again. A draft that never got one is
    # only ever an unfinished import, so dropping it is the honest reverse of
    # the rule above — leaving it would fail the NOT NULL anyway.
    op.execute(
        sa.text("DELETE FROM blog_posts WHERE primary_brand_id IS NULL"),
    )
    op.drop_constraint("brand_unless_draft", "blog_posts", type_="check")
    op.alter_column(
        "blog_posts", "primary_brand_id", existing_type=postgresql.UUID(), nullable=False
    )
