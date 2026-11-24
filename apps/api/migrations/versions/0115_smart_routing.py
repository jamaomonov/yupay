"""Smart routing: automatic supplier choice for managed rules (ADR-0108, part 2).

Revision ID: 0115_smart_routing
Revises: 0114_sourcing_settings
Create Date: 2026-11-24

- ``sku_sourcing_rules.managed`` — the hourly job may move this rule's supplier.
  The rule stays ``force_supplier``, so everything that reads a route keeps
  reading it the same way; an operator's own save clears the flag (a pin).
- ``sourcing_settings.smart_*`` — ``off`` (default) / ``shadow`` / ``on`` and
  the thresholds the data chose: switch at 1 % cheaper, 6 h before switching
  back, at most 6 % dearer when the current supplier cannot sell.
- ``sourcing_switch_log`` — every switch made or, in shadow, proposed.
- ``sourcing_quarantine`` — a supplier that keeps failing one SKU sits out.
- ``supplier_price_state`` — each mapping's last good price and when it was
  last checked. ``supplier_price_history`` records only moves, so it cannot
  tell an unchanged price from one nobody could fetch for hours.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0115_smart_routing"
down_revision: str | None = "0114_sourcing_settings"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "sku_sourcing_rules",
        sa.Column("managed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "sourcing_settings",
        sa.Column("smart_mode", sa.String(16), nullable=False, server_default="off"),
    )
    op.add_column(
        "sourcing_settings",
        sa.Column("smart_switch_pct", sa.Numeric(6, 2), nullable=False, server_default="1"),
    )
    op.add_column(
        "sourcing_settings",
        sa.Column("smart_dwell_hours", sa.Integer(), nullable=False, server_default="6"),
    )
    op.add_column(
        "sourcing_settings",
        sa.Column("smart_stock_step_pct", sa.Numeric(6, 2), nullable=False, server_default="6"),
    )
    op.create_check_constraint(
        "ck_sourcing_settings_smart_mode",
        "sourcing_settings",
        "smart_mode IN ('off','shadow','on')",
    )
    op.create_table(
        "sourcing_switch_log",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "sku_id",
            UUID(as_uuid=False),
            sa.ForeignKey("skus.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_supplier", sa.String(32), nullable=True),
        sa.Column("to_supplier", sa.String(32), nullable=True),
        sa.Column("from_cost_usdt", sa.Numeric(20, 6), nullable=True),
        sa.Column("to_cost_usdt", sa.Numeric(20, 6), nullable=True),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_sourcing_switch_log_sku_created", "sourcing_switch_log", ["sku_id", "created_at"]
    )
    op.create_index("ix_sourcing_switch_log_created", "sourcing_switch_log", ["created_at"])
    op.create_table(
        "sourcing_quarantine",
        sa.Column(
            "sku_id",
            UUID(as_uuid=False),
            sa.ForeignKey("skus.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("supplier_slug", sa.String(32), primary_key=True),
        sa.Column("until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("strikes", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "supplier_price_state",
        sa.Column(
            "sku_id",
            UUID(as_uuid=False),
            sa.ForeignKey("skus.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("supplier_slug", sa.String(32), primary_key=True),
        sa.Column("cost_usdt", sa.Numeric(20, 6), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("supplier_price_state")
    op.drop_table("sourcing_quarantine")
    op.drop_index("ix_sourcing_switch_log_created", table_name="sourcing_switch_log")
    op.drop_index("ix_sourcing_switch_log_sku_created", table_name="sourcing_switch_log")
    op.drop_table("sourcing_switch_log")
    op.drop_constraint("ck_sourcing_settings_smart_mode", "sourcing_settings", type_="check")
    for col in ("smart_stock_step_pct", "smart_dwell_hours", "smart_switch_pct", "smart_mode"):
        op.drop_column("sourcing_settings", col)
    op.drop_column("sku_sourcing_rules", "managed")
