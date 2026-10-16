"""brands — one game, many regions (ADR-0099).

Revision ID: 0101_brand_regions
Revises: 0100_user_purchase_policy
Create Date: 2026-10-16

A region of a game is its own brand (ADR-0079: a brand is one supplier game),
and until now the pairing was a slug convention, ``<slug>`` ↔ ``<slug>-ru``.
That held for two pairs and cannot hold for nine regions, so the link becomes
a column: ``region_parent_id`` names the game's main brand and ``region_code``
the region. The storefront lists only main brands and switches regions on
the game's page.

Links the regions that exist today, by slug, so dev and prod end up alike
(a missing slug simply matches nothing). Visibility is not touched: a region
shows up on the storefront only while its brand is ``visible_retail``.

Reviews follow the game, not the region: reviews filed on a regional brand
move to its main brand, and the stats rows of every affected brand are
rebuilt from the published reviews.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0101_brand_regions"
down_revision: str | None = "0100_user_purchase_policy"
branch_labels: str | None = None
depends_on: str | None = None

#: (main brand slug, regional brand slug, region code).
_LINKS: tuple[tuple[str, str, str], ...] = (
    ("mobile-legends", "mobile-legends-ru", "ru"),
    ("mobile-legends", "mobile-legends-ph", "ph"),
    ("mobile-legends", "mobile-legends-my", "my"),
    ("mobile-legends", "mobile-legends-sg", "sg"),
    ("mobile-legends", "mobile-legends-id", "id"),
    ("mobile-legends", "mobile-legends-tr", "tr"),
    ("mobile-legends", "mobile-legends-us", "us"),
    ("mobile-legends", "mobile-legends-br", "br"),
    ("magic-chess-gogo", "magic-chess-gogo-ru", "ru"),
    ("magic-chess-gogo", "magic-chess-gogo-my", "my"),
    ("magic-chess-gogo", "magic-chess-gogo-ph", "ph"),
    ("magic-chess-gogo", "magic-chess-gogo-tr", "tr"),
)

_RECOMPUTE = """
WITH agg AS (
    SELECT brand_id,
           count(*) AS n,
           coalesce(sum(rating), 0) AS s,
           count(*) FILTER (WHERE rating = 1) AS c1,
           count(*) FILTER (WHERE rating = 2) AS c2,
           count(*) FILTER (WHERE rating = 3) AS c3,
           count(*) FILTER (WHERE rating = 4) AS c4,
           count(*) FILTER (WHERE rating = 5) AS c5
    FROM reviews
    WHERE status = 'published' AND brand_id IN (SELECT id FROM affected)
    GROUP BY brand_id
)
UPDATE brand_rating_stats st
SET count = coalesce(agg.n, 0),
    sum_rating = coalesce(agg.s, 0),
    avg = CASE WHEN coalesce(agg.n, 0) = 0 THEN 0 ELSE round(agg.s::numeric / agg.n, 2) END,
    count_1 = coalesce(agg.c1, 0),
    count_2 = coalesce(agg.c2, 0),
    count_3 = coalesce(agg.c3, 0),
    count_4 = coalesce(agg.c4, 0),
    count_5 = coalesce(agg.c5, 0),
    updated_at = now()
FROM affected
LEFT JOIN agg ON agg.brand_id = affected.id
WHERE st.brand_id = affected.id
"""

_INSERT_MISSING = """
INSERT INTO brand_rating_stats
    (brand_id, count, sum_rating, avg, count_1, count_2, count_3, count_4, count_5)
SELECT b.id, 0, 0, 0, 0, 0, 0, 0, 0
FROM brands b
WHERE b.id IN (SELECT id FROM affected)
ON CONFLICT (brand_id) DO NOTHING
"""


def upgrade() -> None:
    op.add_column(
        "brands",
        sa.Column(
            "region_parent_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("brands.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column("brands", sa.Column("region_code", sa.String(8), nullable=True))
    # Bare suffixes: the naming convention adds the ``ck_brands_`` prefix (core/db.py).
    op.create_check_constraint(
        "region_pair",
        "brands",
        "(region_parent_id IS NULL) = (region_code IS NULL)",
    )
    op.create_check_constraint(
        "region_not_self", "brands", "region_parent_id IS NULL OR region_parent_id <> id"
    )
    op.create_index("ix_brands_region_parent", "brands", ["region_parent_id"])
    op.create_index(
        "uq_brands_region_code",
        "brands",
        ["region_parent_id", "region_code"],
        unique=True,
        postgresql_where=sa.text("region_parent_id IS NOT NULL"),
    )

    bind = op.get_bind()
    for parent, child, code in _LINKS:
        bind.execute(
            sa.text(
                "UPDATE brands c SET region_parent_id = p.id, region_code = :code "
                "FROM brands p WHERE p.slug = :parent AND c.slug = :child "
                "AND p.region_parent_id IS NULL"
            ),
            {"parent": parent, "child": child, "code": code},
        )

    # Reviews of a region belong to the game.
    bind.execute(
        sa.text(
            "CREATE TEMP TABLE affected ON COMMIT DROP AS "
            "SELECT DISTINCT unnest(ARRAY[c.id, c.region_parent_id]) AS id "
            "FROM brands c WHERE c.region_parent_id IS NOT NULL"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE reviews r SET brand_id = c.region_parent_id "
            "FROM brands c WHERE r.brand_id = c.id AND c.region_parent_id IS NOT NULL"
        )
    )
    bind.execute(sa.text(_INSERT_MISSING))
    bind.execute(sa.text(_RECOMPUTE))
    bind.execute(sa.text("DROP TABLE affected"))


def downgrade() -> None:
    # Moved reviews stay on the main brand: which region each came from is not
    # recorded, and the order it belongs to still says.
    op.drop_index("uq_brands_region_code", table_name="brands")
    op.drop_index("ix_brands_region_parent", table_name="brands")
    op.drop_constraint("region_not_self", "brands", type_="check")
    op.drop_constraint("region_pair", "brands", type_="check")
    op.drop_column("brands", "region_code")
    op.drop_column("brands", "region_parent_id")
