"""brand_translations.seo_title / seo_description: per-brand search copy.

Revision ID: 0092_brand_seo_copy
Revises: 0091_skin_items_team
Create Date: 2026-10-01

Every brand page's title came from one template («{name} — пополнение в
Узбекистане»), which cannot say what each game's buyers search for — «mlbb
diamond», «алмазы млбб». Both columns are optional; the template stays the
fallback. Additive and nullable, so the migration is instant and reversible.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0092_brand_seo_copy"
down_revision: str | None = "0091_skin_items_team"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("brand_translations", sa.Column("seo_title", sa.String(120), nullable=True))
    op.add_column("brand_translations", sa.Column("seo_description", sa.String(320), nullable=True))


def downgrade() -> None:
    op.drop_column("brand_translations", "seo_description")
    op.drop_column("brand_translations", "seo_title")
