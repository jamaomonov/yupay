"""Brand reviews, abuse reports, and denormalized per-brand rating stats.

See docs/decisions/0039-reviews-and-ratings.md.

Revision ID: 0034_reviews
Revises: 0033_idempotent_responses
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0034_reviews"
down_revision: str | None = "0033_idempotent_responses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "brand_id",
            UUID(as_uuid=False),
            sa.ForeignKey("brands.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("rating", sa.SmallInteger, nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'published'")),
        sa.Column("locale", sa.String(3), nullable=False, server_default=sa.text("'ru'")),
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
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
        sa.UniqueConstraint("user_id", "order_id", "brand_id", name="uq_reviews_user_order_brand"),
    )
    op.create_index(
        "ix_reviews_brand_status_created", "reviews", ["brand_id", "status", "created_at"]
    )
    op.create_index("ix_reviews_user", "reviews", ["user_id"])

    op.create_table(
        "review_reports",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "review_id",
            UUID(as_uuid=False),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reporter_user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "review_id", "reporter_user_id", name="uq_review_reports_review_reporter"
        ),
    )
    op.create_index("ix_review_reports_review", "review_reports", ["review_id"])

    op.create_table(
        "brand_rating_stats",
        sa.Column(
            "brand_id",
            UUID(as_uuid=False),
            sa.ForeignKey("brands.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("sum_rating", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("avg", sa.Numeric(3, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("count_1", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("count_2", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("count_3", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("count_4", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("count_5", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("brand_rating_stats")
    op.drop_index("ix_review_reports_review", table_name="review_reports")
    op.drop_table("review_reports")
    op.drop_index("ix_reviews_user", table_name="reviews")
    op.drop_index("ix_reviews_brand_status_created", table_name="reviews")
    op.drop_table("reviews")
