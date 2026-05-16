"""Catalog: categories, products, SKUs, translations, price overrides.

Revision ID: 0003_catalog_init
Revises: 0002_fx_init
Create Date: 2026-05-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_catalog_init"
down_revision: str | None = "0002_fx_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("icon", sa.String(64), nullable=True),
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
    op.create_index(
        "ix_categories_active_sort",
        "categories",
        ["sort_order", "slug"],
        postgresql_where=sa.text("active = true"),
    )

    op.create_table(
        "category_translations",
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(8), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("category_id", "locale", name="pk_category_translations"),
    )

    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("slug", sa.String(128), nullable=False, unique=True),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # 'top_up' (direct credit via supplier API) | 'voucher' (code delivery)
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("supplier_hint", sa.String(64), nullable=True),
        sa.Column("image_url", sa.String(1024), nullable=True),
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
        sa.CheckConstraint("kind IN ('top_up', 'voucher')", name="ck_products_kind"),
    )
    op.create_index("ix_products_category", "products", ["category_id"])
    op.create_index(
        "ix_products_active_sort",
        "products",
        ["category_id", "sort_order", "slug"],
        postgresql_where=sa.text("active = true"),
    )

    op.create_table(
        "product_translations",
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(8), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("short_description", sa.String(512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("product_id", "locale", name="pk_product_translations"),
    )

    op.create_table(
        "skus",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sku_code", sa.String(64), nullable=False, unique=True),
        sa.Column("denomination", sa.String(64), nullable=True),
        sa.Column("region", sa.String(8), nullable=True),
        sa.Column("price_usd", sa.Numeric(20, 6), nullable=False),
        sa.Column("image_url", sa.String(1024), nullable=True),
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
        sa.CheckConstraint("price_usd > 0", name="ck_skus_price_positive"),
    )
    op.create_index("ix_skus_product", "skus", ["product_id"])
    op.create_index(
        "ix_skus_active_sort",
        "skus",
        ["product_id", "sort_order"],
        postgresql_where=sa.text("active = true"),
    )

    op.create_table(
        "sku_prices",
        sa.Column(
            "sku_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("skus.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # ISO 4217 fiat code OR 'USDT'/'USDC' etc.
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("price", sa.Numeric(20, 6), nullable=False),
        sa.PrimaryKeyConstraint("sku_id", "currency", name="pk_sku_prices"),
        sa.CheckConstraint("price > 0", name="ck_sku_prices_positive"),
    )


def downgrade() -> None:
    op.drop_table("sku_prices")
    op.drop_index("ix_skus_active_sort", table_name="skus")
    op.drop_index("ix_skus_product", table_name="skus")
    op.drop_table("skus")
    op.drop_table("product_translations")
    op.drop_index("ix_products_active_sort", table_name="products")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_table("products")
    op.drop_table("category_translations")
    op.drop_index("ix_categories_active_sort", table_name="categories")
    op.drop_table("categories")
