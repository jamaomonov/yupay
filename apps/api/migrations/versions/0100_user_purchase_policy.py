"""users — per-account purchase limit and the trusted flag.

Revision ID: 0100_user_purchase_policy
Revises: 0099_affiliate_clicks
Create Date: 2026-10-11

An operator can cap what one account may ever buy (``purchase_limit_usd``, a
lifetime total across its orders and guest orders under its email) and can mark
an account trusted (``trusted_at``), which skips every review rule and the
pre-charge veto. See ``orders.account_policy``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0100_user_purchase_policy"
down_revision: str | None = "0099_affiliate_clicks"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("purchase_limit_usd", sa.Numeric(12, 2), nullable=True))
    op.add_column("users", sa.Column("trusted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "trusted_by",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Bare suffix: the naming convention adds the ``ck_users_`` prefix (core/db.py).
    op.create_check_constraint(
        "purchase_limit_usd_non_negative", "users", "purchase_limit_usd >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("purchase_limit_usd_non_negative", "users", type_="check")
    op.drop_column("users", "trusted_by")
    op.drop_column("users", "trusted_at")
    op.drop_column("users", "purchase_limit_usd")
