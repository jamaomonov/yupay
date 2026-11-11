"""usdt_settings, usdt_reservations, usdt_incoming — reseller USDT (TRC20) top-up.

Revision ID: 0111_usdt_deposit
Revises: 0110_admin_sessions
Create Date: 2026-11-11

New tables only; nothing existing changes. ADR-0104. Check constraints take the bare
suffix: the naming convention adds ``ck_<table>_`` (core/db.py).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0111_usdt_deposit"
down_revision: str | None = "0110_admin_sessions"
branch_labels: str | None = None
depends_on: str | None = None

UUID = pg.UUID(as_uuid=False)
NOW = sa.text("CURRENT_TIMESTAMP")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "usdt_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("mode", sa.String(16), nullable=False, server_default="off"),
        sa.Column("allowlist_merchant_ids", pg.ARRAY(UUID), nullable=False, server_default="{}"),
        sa.Column("address", sa.String(34), nullable=True),
        sa.Column("min_amount_usd", sa.Numeric(18, 2), nullable=False, server_default="10"),
        sa.Column("max_amount_usd", sa.Numeric(18, 2), nullable=False, server_default="50000"),
        sa.Column("cursor_block_ms", sa.BigInteger, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint("id = 1", name="singleton"),
        sa.CheckConstraint("mode IN ('off','allowlist','all')", name="mode"),
        sa.CheckConstraint(
            "min_amount_usd > 0 AND max_amount_usd >= min_amount_usd",
            name="bounds",
        ),
    )
    op.execute("INSERT INTO usdt_settings (id) VALUES (1)")

    op.create_table(
        "usdt_reservations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("number", sa.String(8), nullable=False),
        sa.Column("merchant_id", UUID, sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("address", sa.String(34), nullable=False),
        sa.Column("amount_usdt", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("holds_amount", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("closed_at", TS, nullable=True),
        sa.Column("quarantine_until", TS, nullable=True),
        sa.Column("incoming_id", UUID, nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.UniqueConstraint("number", name="uq_usdt_reservations_number"),
        sa.CheckConstraint(
            "status IN ('pending','paid','expired','cancelled')",
            name="status",
        ),
        sa.CheckConstraint("amount_usdt > 0", name="amount"),
    )
    op.create_index(
        "uq_usdt_reservations_open_amount",
        "usdt_reservations",
        ["amount_usdt"],
        unique=True,
        postgresql_where=sa.text("holds_amount"),
    )
    op.create_index(
        "uq_usdt_reservations_one_pending",
        "usdt_reservations",
        ["merchant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_usdt_reservations_idem",
        "usdt_reservations",
        ["merchant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_usdt_reservations_sweep", "usdt_reservations", ["status", "expires_at"])
    op.create_index(
        "ix_usdt_reservations_match", "usdt_reservations", ["amount_usdt", "created_at"]
    )

    op.create_table(
        "usdt_incoming",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tx_id", sa.String(64), nullable=False),
        sa.Column("from_address", sa.String(34), nullable=False),
        sa.Column("to_address", sa.String(34), nullable=False),
        sa.Column("amount_usdt", sa.Numeric(24, 6), nullable=False),
        sa.Column("block_at", TS, nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("reservation_id", UUID, nullable=True),
        sa.Column("merchant_id", UUID, nullable=True),
        sa.Column("resolved_by", UUID, nullable=True),
        sa.Column("resolved_at", TS, nullable=True),
        sa.Column("note", sa.String(256), nullable=True),
        sa.Column("received_at", TS, nullable=False),
        sa.UniqueConstraint("tx_id", name="uq_usdt_incoming_tx_id"),
        sa.CheckConstraint(
            "result IN ('matched','unmatched','ignored','manual','dismissed')",
            name="result",
        ),
    )
    op.create_index("ix_usdt_incoming_block_at", "usdt_incoming", ["block_at"])
    op.create_index("ix_usdt_incoming_result", "usdt_incoming", ["result"])


def downgrade() -> None:
    op.drop_table("usdt_incoming")
    op.drop_table("usdt_reservations")
    op.drop_table("usdt_settings")
