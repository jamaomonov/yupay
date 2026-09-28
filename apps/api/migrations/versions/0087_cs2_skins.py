"""CS2 skins: item catalogue, settings singleton, search aliases (ADR-0093).

Revision ID: 0087_cs2_skins
Revises: 0086_catalog_cache_voucher_denom
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0087_cs2_skins"
down_revision: str | None = "0086_catalog_cache_voucher_denom"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Present on prod via infra/postgres/init; the test container starts bare.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "skin_items",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("market_hash_name", sa.String(255), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False, server_default=sa.text("''")),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("weapon", sa.String(64), nullable=True),
        sa.Column("skin", sa.String(128), nullable=True),
        sa.Column("exterior", sa.String(2), nullable=True),
        sa.Column("stattrak", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("souvenir", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rarity", sa.String(64), nullable=True),
        sa.Column("rarity_color", sa.String(9), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("min_float", sa.Numeric(6, 5), nullable=True),
        sa.Column("max_float", sa.Numeric(6, 5), nullable=True),
        sa.Column("paint_index", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default=sa.text("'stub'")),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("steam_price_units", sa.BigInteger(), nullable=True),
        sa.Column("min_auto_units", sa.BigInteger(), nullable=True),
        sa.Column("count_auto", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cheapest_auto", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("min_all_units", sa.BigInteger(), nullable=True),
        sa.Column("count_all", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("price_hash", sa.String(40), nullable=True),
        sa.Column("prices_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("margin_override_pp", sa.Numeric(6, 2), nullable=True),
        sa.Column("fixed_price_usd", sa.Numeric(12, 2), nullable=True),
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
        sa.UniqueConstraint("market_hash_name", "phase", name="uq_skin_items_name_phase"),
        sa.UniqueConstraint("slug", name="uq_skin_items_slug"),
    )
    op.create_index("ix_skin_items_category_price", "skin_items", ["category", "min_auto_units"])
    op.create_index("ix_skin_items_weapon", "skin_items", ["weapon"])
    op.create_index("ix_skin_items_active", "skin_items", ["active"])
    op.create_index(
        "ix_skin_items_search_trgm",
        "skin_items",
        ["search_text"],
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.create_table(
        "skin_pricing_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rules", JSONB(), nullable=False),
        sa.Column("updated_by", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("id = 1", name="ck_skin_pricing_rules_singleton"),
    )
    op.create_table(
        "skin_search_aliases",
        sa.Column("alias", sa.String(64), primary_key=True),
        sa.Column("text", sa.String(128), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("skin_search_aliases")
    op.drop_table("skin_pricing_rules")
    op.drop_index("ix_skin_items_search_trgm", table_name="skin_items")
    op.drop_index("ix_skin_items_active", table_name="skin_items")
    op.drop_index("ix_skin_items_weapon", table_name="skin_items")
    op.drop_index("ix_skin_items_category_price", table_name="skin_items")
    op.drop_table("skin_items")
