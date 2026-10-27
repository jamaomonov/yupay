"""``brands.variant_parent_id`` / ``variant_code``: one game, two ways to buy it, two pages.

Standoff 2 sells Gold by player id (``standoff-2-id``) and as promo codes
(``standoff-2``). The catalogue should show one «Standoff 2»; each page should offer the
other. That is close to a game's regions (ADR-0099, migration 0101) but not the same: a
region's page redirects to the game's page with ``?region=``, while a variant keeps its
own page, URL and search copy — the promo page is the one with the search history — and
the switcher between them is a pair of links.

The main variant (listed in the catalogue, opened by default) has no parent and may
carry a code; every other variant points at it and must. Labels come from the
storefront's message catalogue by code (``id``, ``promo``).

Revision ID: 0108_brand_variants
Revises: 0107_brand_maintenance_redirect
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0108_brand_variants"
down_revision: str | None = "0107_brand_maintenance_redirect"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "brands",
        sa.Column(
            "variant_parent_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("brands.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column("brands", sa.Column("variant_code", sa.String(16), nullable=True))
    # Bare suffixes: the naming convention adds the ``ck_brands_`` prefix (core/db.py).
    op.create_check_constraint(
        "variant_code_set", "brands", "variant_parent_id IS NULL OR variant_code IS NOT NULL"
    )
    op.create_check_constraint(
        "variant_not_self", "brands", "variant_parent_id IS NULL OR variant_parent_id <> id"
    )
    op.create_index("ix_brands_variant_parent", "brands", ["variant_parent_id"])


def downgrade() -> None:
    op.drop_index("ix_brands_variant_parent", table_name="brands")
    op.drop_constraint("variant_not_self", "brands", type_="check")
    op.drop_constraint("variant_code_set", "brands", type_="check")
    op.drop_column("brands", "variant_code")
    op.drop_column("brands", "variant_parent_id")
