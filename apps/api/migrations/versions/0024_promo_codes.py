"""Promo codes: fixed-denomination wallet gifts.

``promo_codes`` holds the issuable codes; ``promo_redemptions`` records who
took what (UNIQUE per code+user) and links to the ledger transaction that
carried the credit. See ADR-0029.

Revision ID: 0024_promo_codes
Revises: 0023_payment_idempotency
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0024_promo_codes"
down_revision: str | None = "0023_payment_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("amount > 0", name="ck_promo_codes_amount_positive"),
    )
    op.create_table(
        "promo_redemptions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "promo_code_id",
            UUID(as_uuid=False),
            sa.ForeignKey("promo_codes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            UUID(as_uuid=False),
            sa.ForeignKey("wallet_transactions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("promo_code_id", "user_id", name="uq_promo_redemptions_code_user"),
    )
    op.create_index("ix_promo_redemptions_user", "promo_redemptions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_promo_redemptions_user", table_name="promo_redemptions")
    op.drop_table("promo_redemptions")
    op.drop_table("promo_codes")
