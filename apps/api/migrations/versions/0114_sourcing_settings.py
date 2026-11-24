"""``sourcing_settings``: the smart-sourcing switches (ADR-0108).

Revision ID: 0114_sourcing_settings
Revises: 0113_sku_one_time_pack
Create Date: 2026-11-24

One row, ``id = 1``, seeded with automatic failover **off** — the behaviour
before this ADR. The owner switches it on in the admin.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0114_sourcing_settings"
down_revision: str | None = "0113_sku_one_time_pack"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "sourcing_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("failover_mode", sa.String(16), nullable=False, server_default="off"),
        sa.Column(
            "failover_min_margin_retail_pct", sa.Numeric(6, 2), nullable=False, server_default="3"
        ),
        sa.Column(
            "failover_min_margin_b2b_pct", sa.Numeric(6, 2), nullable=False, server_default="0"
        ),
        sa.Column("failover_max_step_pct", sa.Numeric(6, 2), nullable=False, server_default="6"),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "failover_mode IN ('off','retail','all')", name="ck_sourcing_settings_failover_mode"
        ),
    )
    op.execute("INSERT INTO sourcing_settings (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("sourcing_settings")
