"""``payment_review_limits``: per-provider spend a buyer may pay before a human looks.

One row per payment slug. When a buyer's settled payments through that slug in the last
``window_hours`` — this one included — come to more than ``max_amount``, the order is held
for review instead of fulfilled (a wallet top-up is held instead of credited). Summing the
window is the point: a limit on a single payment is one a carder splits into two.

Seeded with the owner's rule of 2026-10-21: Click's mini-app kassa, 90 000 soʻm a day.
Editable in the admin afterwards; the seed is only where it starts.

The partial index serves the window sum (settled payments through one provider since a
moment) and nothing else reads that shape today.

Revision ID: 0104_payment_review_limits
Revises: 0103_user_signup_source
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0104_payment_review_limits"
down_revision: str | None = "0103_user_signup_source"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "payment_review_limits",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("max_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'UZS'")),
        sa.Column("window_hours", sa.Integer(), nullable=False, server_default=sa.text("24")),
        sa.Column("changed_by", UUID(as_uuid=False), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("max_amount > 0", name="ck_payment_review_limits_max_amount_positive"),
        sa.CheckConstraint(
            "window_hours BETWEEN 1 AND 720", name="ck_payment_review_limits_window_hours_range"
        ),
    )
    op.execute(
        "INSERT INTO payment_review_limits (provider, enabled, max_amount, currency, window_hours)"
        " VALUES ('click_miniapp', true, 90000, 'UZS', 24)"
    )
    op.execute("SET lock_timeout = '3s'")
    op.create_index(
        "ix_payments_provider_succeeded_at",
        "payments",
        ["provider", "succeeded_at"],
        postgresql_where=sa.text("status = 'succeeded'"),
    )
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    op.drop_index("ix_payments_provider_succeeded_at", table_name="payments")
    op.drop_table("payment_review_limits")
