"""Wallet skeleton: wallet_accounts, wallet_transactions, wallet_postings.

See ADR-0014.

Revision ID: 0009_wallet_init
Revises: 0008_fulfillment_init
Create Date: 2026-05-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_wallet_init"
down_revision: str | None = "0008_fulfillment_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OWNER_TYPES = ("user", "house", "provider")
_ACCOUNT_STATUSES = ("active", "frozen")
_ACCOUNT_KINDS = (
    "user_wallet",
    "user_cashback",
    "user_promo_credit",
    "house_revenue",
    "house_cogs",
    "house_promo_expense",
    "house_refunds",
    "house_fx_pnl",
    "provider_clearing",
)
_DIRECTIONS = ("D", "C")


def upgrade() -> None:
    op.create_table(
        "wallet_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_type", sa.String(16), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "owner_type IN " + repr(_OWNER_TYPES), name="ck_wallet_accounts_owner_type"
        ),
        sa.CheckConstraint(
            "status IN " + repr(_ACCOUNT_STATUSES),
            name="ck_wallet_accounts_status",
        ),
        sa.CheckConstraint(
            "kind IN " + repr(_ACCOUNT_KINDS), name="ck_wallet_accounts_kind"
        ),
        sa.UniqueConstraint(
            "owner_type",
            "owner_id",
            "kind",
            "currency",
            name="uq_wallet_accounts_owner_kind_currency",
        ),
    )
    op.create_index(
        "ix_wallet_accounts_owner",
        "wallet_accounts",
        ["owner_type", "owner_id"],
    )

    op.create_table(
        "wallet_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("reference_type", sa.String(32), nullable=True),
        sa.Column("reference_id", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("actor", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_wallet_transactions_idempotency_key"
        ),
    )
    op.create_index(
        "ix_wallet_transactions_reference",
        "wallet_transactions",
        ["reference_type", "reference_id"],
    )

    op.create_table(
        "wallet_postings",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("wallet_transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("wallet_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("direction", sa.CHAR(1), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("amount > 0", name="ck_wallet_postings_amount_positive"),
        sa.CheckConstraint(
            "direction IN " + repr(_DIRECTIONS),
            name="ck_wallet_postings_direction",
        ),
    )
    op.create_index(
        "ix_wallet_postings_account_created",
        "wallet_postings",
        ["account_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_wallet_postings_transaction",
        "wallet_postings",
        ["transaction_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_wallet_postings_transaction", table_name="wallet_postings")
    op.drop_index(
        "ix_wallet_postings_account_created", table_name="wallet_postings"
    )
    op.drop_table("wallet_postings")
    op.drop_index(
        "ix_wallet_transactions_reference", table_name="wallet_transactions"
    )
    op.drop_table("wallet_transactions")
    op.drop_index("ix_wallet_accounts_owner", table_name="wallet_accounts")
    op.drop_table("wallet_accounts")
