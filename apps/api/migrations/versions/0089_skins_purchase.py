"""Skins purchase: trades mirrored per order line, saved trade links, mapping kind ``skin``.

Revision ID: 0089_skins_purchase
Revises: 0088_skins_sell_price
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0089_skins_purchase"
down_revision: str | None = "0088_skins_sell_price"
branch_labels: str | None = None
depends_on: str | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "skin_trades",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "order_item_id",
            UUID(as_uuid=False),
            sa.ForeignKey("order_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            UUID(as_uuid=False),
            sa.ForeignKey("fulfillment_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("waxpeer_id", sa.BigInteger(), nullable=True),
        sa.Column("listing_id", sa.BigInteger(), nullable=False),
        sa.Column("market_hash_name", sa.String(255), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False, server_default=sa.text("''")),
        sa.Column("paid_units", sa.Integer(), nullable=False),
        sa.Column("bought_units", sa.Integer(), nullable=True),
        sa.Column("status", sa.SmallInteger(), nullable=True),
        sa.Column("trade_id", sa.String(32), nullable=True),
        sa.Column("send_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_released", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("penalties", JSONB(), nullable=True),
        sa.Column("seller", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("order_item_id", name="uq_skin_trades_order_item"),
        sa.UniqueConstraint("project_id", name="uq_skin_trades_project"),
    )
    op.create_index("ix_skin_trades_protection", "skin_trades", ["status", "is_released"])
    op.create_table(
        "skin_trade_links",
        sa.Column(
            "user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("url", sa.String(255), nullable=False),
        sa.Column("steam_id", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.drop_constraint("ck_sku_supplier_mapping_kind", "sku_supplier_mapping", type_="check")
    op.create_check_constraint(
        "ck_sku_supplier_mapping_kind",
        "sku_supplier_mapping",
        "kind IN ('voucher','game','gift','skin')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sku_supplier_mapping_kind", "sku_supplier_mapping", type_="check")
    op.create_check_constraint(
        "ck_sku_supplier_mapping_kind",
        "sku_supplier_mapping",
        "kind IN ('voucher','game','gift')",
    )
    op.drop_table("skin_trade_links")
    op.drop_index("ix_skin_trades_protection", table_name="skin_trades")
    op.drop_table("skin_trades")
