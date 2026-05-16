"""Catalog: introduce ``brands`` (3rd level) and ``products.required_fields``.

See ADR-0009. The product layout becomes:

    Category → Brand → Product → SKU

``products.category_id`` is replaced by ``products.brand_id`` — categories are reached
transitively through the brand. ``required_fields`` carries the storefront form schema.

Revision ID: 0004_catalog_brands
Revises: 0003_catalog_init
Create Date: 2026-05-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_catalog_brands"
down_revision: str | None = "0003_catalog_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) brands
    op.create_table(
        "brands",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("logo_url", sa.String(1024), nullable=True),
        sa.Column("hero_image_url", sa.String(1024), nullable=True),
        sa.Column("accent_color", sa.String(16), nullable=True),
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
    op.create_index("ix_brands_category", "brands", ["category_id"])
    op.create_index(
        "ix_brands_active_sort",
        "brands",
        ["category_id", "sort_order", "slug"],
        postgresql_where=sa.text("active = true"),
    )

    op.create_table(
        "brand_translations",
        sa.Column(
            "brand_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("brands.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(8), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("short_description", sa.String(512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("brand_id", "locale", name="pk_brand_translations"),
    )

    # 2) products: add new columns nullable, backfill, then enforce NOT NULL.
    op.add_column(
        "products",
        sa.Column("brand_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column(
            "required_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # Backfill: for every existing product, create a brand 1:1 (slug + ru/en/uz fallback
    # name = product.slug). In dev there is typically nothing here, but the migration is
    # safe to run against a populated DB too.
    op.execute(
        """
        INSERT INTO brands (id, slug, category_id, sort_order, active, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            'brand-' || p.slug,
            p.category_id,
            p.sort_order,
            p.active,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM products p
        WHERE NOT EXISTS (SELECT 1 FROM brands b WHERE b.slug = 'brand-' || p.slug)
        """
    )
    op.execute(
        """
        UPDATE products p
           SET brand_id = b.id
          FROM brands b
         WHERE b.slug = 'brand-' || p.slug
           AND p.brand_id IS NULL
        """
    )
    # Insert a stub translation per backfilled brand (locale=ru) so the listing API
    # has something to render until a human edits it.
    op.execute(
        """
        INSERT INTO brand_translations (brand_id, locale, name)
        SELECT b.id, 'ru', REPLACE(REPLACE(b.slug, 'brand-', ''), '-', ' ')
          FROM brands b
         WHERE NOT EXISTS (
            SELECT 1 FROM brand_translations t
             WHERE t.brand_id = b.id AND t.locale = 'ru'
         )
        """
    )

    op.alter_column("products", "brand_id", nullable=False)
    op.create_foreign_key(
        "fk_products_brand_id_brands",
        "products",
        "brands",
        ["brand_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_products_brand", "products", ["brand_id"])

    # 3) drop the now-redundant direct edge to categories.
    op.drop_index("ix_products_category", table_name="products")
    op.drop_index("ix_products_active_sort", table_name="products")
    op.drop_constraint("fk_products_category_id_categories", "products", type_="foreignkey")
    op.drop_column("products", "category_id")

    op.create_index(
        "ix_products_active_sort",
        "products",
        ["brand_id", "sort_order", "slug"],
        postgresql_where=sa.text("active = true"),
    )


def downgrade() -> None:
    # Re-attach products to categories (best-effort: via their brand).
    op.add_column(
        "products",
        sa.Column("category_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.execute(
        """
        UPDATE products p
           SET category_id = b.category_id
          FROM brands b
         WHERE b.id = p.brand_id
        """
    )
    op.alter_column("products", "category_id", nullable=False)
    op.create_foreign_key(
        "fk_products_category_id_categories",
        "products",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_index("ix_products_active_sort", table_name="products")
    op.create_index("ix_products_category", "products", ["category_id"])
    op.create_index(
        "ix_products_active_sort",
        "products",
        ["category_id", "sort_order", "slug"],
        postgresql_where=sa.text("active = true"),
    )

    op.drop_index("ix_products_brand", table_name="products")
    op.drop_constraint("fk_products_brand_id_brands", "products", type_="foreignkey")
    op.drop_column("products", "required_fields")
    op.drop_column("products", "brand_id")

    op.drop_table("brand_translations")
    op.drop_index("ix_brands_active_sort", table_name="brands")
    op.drop_index("ix_brands_category", table_name="brands")
    op.drop_table("brands")
