"""Paynet UWS transactions.

Revision ID: 0080_paynet
Revises: 0079_blog_import
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0080_paynet"
down_revision: str | None = "0079_blog_import"
branch_labels: str | None = None
depends_on: str | None = None

_TS = sa.DateTime(timezone=True)
_NOW = sa.text("CURRENT_TIMESTAMP")
_SEQ = "paynet_provider_trn_id_seq"


def upgrade() -> None:
    # Paynet types ``providerTrnId`` as a 64-bit integer, and our order ids are
    # UUIDs — so the number has to come from somewhere of its own. Starts at
    # 1000 because a single-digit id in a support chat is indistinguishable
    # from a typo.
    op.execute(sa.text(f"CREATE SEQUENCE {_SEQ} START WITH 1000"))
    op.create_table(
        "paynet_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("paynet_transaction_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "provider_trn_id",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text(f"nextval('{_SEQ}')"),
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payment_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("payments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("amount_tiyin", sa.BigInteger(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.Integer(), nullable=False),
        sa.Column("performed_at", _TS, nullable=False),
        sa.Column("cancelled_at", _TS, nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.PrimaryKeyConstraint("id"),
        # Paynet's own id is the idempotency key: a retried PerformTransaction
        # carries the same value, and this index is what stops a race between
        # two of them charging twice.
        sa.UniqueConstraint("paynet_transaction_id", name="uq_paynet_transactions_external"),
        sa.UniqueConstraint("provider_trn_id", name="uq_paynet_transactions_provider_trn"),
        # 1 successful, 2 cancelled. The enum's third value, 3, means "no such
        # transaction" — the absence of a row, never a value in one.
        sa.CheckConstraint("state IN (1, 2)", name="state_known"),
    )
    op.execute(sa.text(f"ALTER SEQUENCE {_SEQ} OWNED BY paynet_transactions.provider_trn_id"))
    op.create_index("ix_paynet_transactions_order", "paynet_transactions", ["order_id"])
    op.create_index(
        "ix_paynet_transactions_state_performed",
        "paynet_transactions",
        ["state", "performed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_paynet_transactions_state_performed", table_name="paynet_transactions")
    op.drop_index("ix_paynet_transactions_order", table_name="paynet_transactions")
    # The sequence is OWNED BY the column, so the table drop takes it too.
    op.drop_table("paynet_transactions")
