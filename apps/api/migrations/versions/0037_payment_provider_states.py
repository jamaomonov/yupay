"""Admin-controlled payment provider states.

Backs the disable / maintenance controls. One row per gateway slug; absence of a
row means `active`, so nothing is seeded — a provider only gets a row once an
operator changes its state.

Revision ID: 0037_payment_provider_states
Revises: 0036_grandfather_email_verified
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0037_payment_provider_states"
down_revision: str | None = "0036_grandfather_email_verified"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_provider_states",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("changed_by", UUID(as_uuid=False), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('active', 'disabled', 'maintenance')",
            name="ck_payment_provider_states_state",
        ),
    )


def downgrade() -> None:
    op.drop_table("payment_provider_states")
