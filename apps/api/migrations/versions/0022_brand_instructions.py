"""Add ``instructions`` longform to brand translations.

A per-locale "how to top up / supported regions / where to find your ID" guide
shown as an indexable prose section on the brand page (distinct from the short
``description``). Nullable so existing brands are unaffected.

Revision ID: 0022_brand_instructions
Revises: 0021_brand_faqs
Create Date: 2026-06-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_brand_instructions"
down_revision: str | None = "0021_brand_faqs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("brand_translations", sa.Column("instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("brand_translations", "instructions")
