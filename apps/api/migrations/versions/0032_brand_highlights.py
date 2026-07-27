"""Add ``brand_translations.highlights`` (localized value-prop chips).

Nullable JSON list of short strings rendered on the brand hero. Additive and
nullable, so existing rows are untouched.

Revision ID: 0032_brand_highlights
Revises: 0031_uzum_amount_sum_to_tiyin
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_brand_highlights"
down_revision: str | None = "0031_uzum_amount_sum_to_tiyin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "brand_translations",
        sa.Column("highlights", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("brand_translations", "highlights")
