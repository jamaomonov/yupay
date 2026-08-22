"""Per-quote FX override: admin rate + use-manual toggle.

Revision ID: 0050_fx_quote_settings
Revises: 0049_sku_min_max_qty
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0050_fx_quote_settings"
down_revision: str | None = "0049_sku_min_max_qty"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_QUOTES: tuple[str, ...] = ("RUB", "UZS", "USDT")


def upgrade() -> None:
    op.create_table(
        "fx_quote_settings",
        sa.Column("quote", sa.String(8), primary_key=True),
        sa.Column("use_manual", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("manual_rate", sa.Numeric(20, 10), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "manual_rate IS NULL OR manual_rate > 0",
            name="ck_fx_quote_settings_rate_positive",
        ),
        sa.CheckConstraint(
            "NOT use_manual OR (manual_rate IS NOT NULL AND manual_rate > 0)",
            name="ck_fx_quote_settings_manual_complete",
        ),
    )
    op.bulk_insert(
        sa.table("fx_quote_settings", sa.column("quote", sa.String(8))),
        [{"quote": q} for q in _DEFAULT_QUOTES],
    )


def downgrade() -> None:
    op.drop_table("fx_quote_settings")
