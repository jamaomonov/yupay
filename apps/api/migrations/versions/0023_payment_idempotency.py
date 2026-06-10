"""Add ``idempotency_key`` to payments.

``POST /payments/intents`` persists the client's ``Idempotency-Key`` so a
timeout-retry replays the original payment even after the order walked past
``pending_payment``. Nullable (old rows, internal callers); partial UNIQUE
mirrors the orders pattern.

Revision ID: 0023_payment_idempotency
Revises: 0022_brand_instructions
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_payment_idempotency"
down_revision: str | None = "0022_brand_instructions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("idempotency_key", sa.String(128), nullable=True))
    op.create_index(
        "uq_payments_idempotency_key",
        "payments",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_payments_idempotency_key", table_name="payments")
    op.drop_column("payments", "idempotency_key")
