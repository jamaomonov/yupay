"""FX: rate history + checkout snapshots.

Revision ID: 0002_fx_init
Revises: 0001_auth_users_init
Create Date: 2026-05-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_fx_init"
down_revision: str | None = "0001_auth_users_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fx_rates",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("base", sa.String(8), nullable=False),
        sa.Column("quote", sa.String(8), nullable=False),
        # 20 digits with 10 fractional positions — comfortably covers fiat AND crypto.
        sa.Column("rate", sa.Numeric(20, 10), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("rate > 0", name="ck_fx_rates_positive"),
    )
    op.create_index(
        "ix_fx_rates_pair_fetched",
        "fx_rates",
        ["base", "quote", sa.text("fetched_at DESC")],
    )

    op.create_table(
        "fx_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("base", sa.String(8), nullable=False),
        sa.Column("quote", sa.String(8), nullable=False),
        sa.Column("rate", sa.Numeric(20, 10), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("rate > 0", name="ck_fx_snapshots_positive"),
    )
    op.create_index(
        "ix_fx_snapshots_pair_created",
        "fx_snapshots",
        ["base", "quote", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_fx_snapshots_pair_created", table_name="fx_snapshots")
    op.drop_table("fx_snapshots")
    op.drop_index("ix_fx_rates_pair_fetched", table_name="fx_rates")
    op.drop_table("fx_rates")
