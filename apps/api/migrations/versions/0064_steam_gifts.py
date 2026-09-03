"""Steam Gifts: admin-editable margin setting + widen the mapping-kind CHECK.

``steam_gift_settings`` is a singleton table (``id`` pinned to 1 by a CHECK)
holding the one admin-editable margin percent applied to Steam gift
packages. ``sku_supplier_mapping.kind`` grows a third value, ``'gift'``, so a
Steam gift SKU can be mapped to its G-Engine supplier product the same way a
voucher or game top-up is today.

Revision ID: 0064_steam_gifts
Revises: 0063_steam_links
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0064_steam_gifts"
down_revision: str | None = "0063_steam_links"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "steam_gift_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("margin_percent", sa.Numeric(10, 4), nullable=False),
        sa.Column(
            "updated_by",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("margin_percent >= 0", name="ck_steam_gift_settings_margin_nonneg"),
        sa.CheckConstraint("id = 1", name="ck_steam_gift_settings_singleton"),
    )

    op.drop_constraint("ck_sku_supplier_mapping_kind", "sku_supplier_mapping", type_="check")
    op.create_check_constraint(
        "ck_sku_supplier_mapping_kind",
        "sku_supplier_mapping",
        "kind IN ('voucher','game','gift')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sku_supplier_mapping_kind", "sku_supplier_mapping", type_="check")
    op.create_check_constraint(
        "ck_sku_supplier_mapping_kind",
        "sku_supplier_mapping",
        "kind IN ('voucher','game')",
    )

    op.drop_table("steam_gift_settings")
