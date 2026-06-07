"""Per-brand FAQ entries + their localised question/answer rows.

Adds ``brand_faqs`` (one row per FAQ, scoped to a brand, with sort_order/active)
and ``brand_faq_translations`` (ru/en/uz question + answer keyed by locale).
Both cascade-delete with the parent so removing a brand or a FAQ cleans up its
translations. The FAQs are rendered on the brand page and emitted as FAQPage
structured data for SEO.

Revision ID: 0021_brand_faqs
Revises: 0020_user_passwords
Create Date: 2026-06-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_brand_faqs"
down_revision: str | None = "0020_user_passwords"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brand_faqs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "brand_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("brands.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
    )
    op.create_index("ix_brand_faqs_brand_sort", "brand_faqs", ["brand_id", "sort_order"])

    op.create_table(
        "brand_faq_translations",
        sa.Column(
            "brand_faq_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("brand_faqs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column("question", sa.String(length=512), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("brand_faq_id", "locale", name="pk_brand_faq_translations"),
    )


def downgrade() -> None:
    op.drop_table("brand_faq_translations")
    op.drop_index("ix_brand_faqs_brand_sort", table_name="brand_faqs")
    op.drop_table("brand_faqs")
