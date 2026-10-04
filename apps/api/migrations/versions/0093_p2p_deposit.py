"""p2p_cards, p2p_reservations, p2p_incoming, p2p_settings — reseller P2P top-up.

Revision ID: 0093_p2p_deposit
Revises: 0092_brand_seo_copy
Create Date: 2026-10-04

New tables only; nothing existing changes. Spec:
docs/superpowers/specs/2026-10-04-p2p-deposit-design.md §5.2.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0093_p2p_deposit"
down_revision: str | None = "0092_brand_seo_copy"
branch_labels: str | None = None
depends_on: str | None = None

UUID = pg.UUID(as_uuid=False)
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "p2p_cards",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("pan_ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("pan_nonce", sa.LargeBinary, nullable=False),
        sa.Column("pan_last4", sa.String(4), nullable=False),
        sa.Column("holder_name", sa.String(128), nullable=False),
        sa.Column("network", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("min_amount_uzs", sa.Integer, nullable=False, server_default="10000"),
        sa.Column("max_amount_uzs", sa.Integer, nullable=False, server_default="10000000"),
        sa.Column("daily_limit_uzs", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_by", UUID, nullable=True),
        sa.CheckConstraint("network IN ('humo','uzcard')", name="network"),
        sa.CheckConstraint(
            "min_amount_uzs > 0 AND max_amount_uzs >= min_amount_uzs", name="bounds"
        ),
    )
    op.create_table(
        "p2p_reservations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("number", sa.String(8), nullable=False, unique=True),
        sa.Column("card_id", UUID, sa.ForeignKey("p2p_cards.id"), nullable=False),
        sa.Column("amount_uzs", sa.BigInteger, nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("merchant_id", UUID, sa.ForeignKey("merchants.id"), nullable=True),
        sa.Column("fx_rate", sa.Numeric(18, 6), nullable=False),
        sa.Column("fx_snapshot_id", UUID, nullable=True),
        sa.Column("amount_usd", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("holds_amount", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quarantine_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("incoming_id", UUID, nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.CheckConstraint("status IN ('pending','paid','expired','cancelled')", name="status"),
        sa.CheckConstraint("purpose IN ('merchant_deposit')", name="purpose"),
        sa.CheckConstraint("amount_uzs > 0", name="amount"),
    )
    op.create_index(
        "uq_p2p_reservations_open_amount",
        "p2p_reservations",
        ["card_id", "amount_uzs"],
        unique=True,
        postgresql_where=sa.text("holds_amount"),
    )
    op.create_index(
        "uq_p2p_reservations_one_pending",
        "p2p_reservations",
        ["merchant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_p2p_reservations_idem",
        "p2p_reservations",
        ["merchant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_p2p_reservations_sweep", "p2p_reservations", ["status", "expires_at"])
    op.create_table(
        "p2p_incoming",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("business_connection_id", sa.String(128), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("amount_uzs", sa.Numeric(18, 2), nullable=True),
        sa.Column("source_text", sa.String(128), nullable=True),
        sa.Column("card_last4", sa.String(4), nullable=True),
        sa.Column("bank_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("balance_after", sa.Numeric(18, 2), nullable=True),
        sa.Column("chain_ok", sa.Boolean, nullable=True),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("reservation_id", UUID, nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "business_connection_id", "telegram_message_id", name="uq_p2p_incoming_message"
        ),
        sa.CheckConstraint("kind IN ('credit','debit','unparsed')", name="kind"),
        sa.CheckConstraint("result IN ('matched','unmatched','ignored')", name="result"),
    )
    op.create_index("ix_p2p_incoming_card_time", "p2p_incoming", ["card_last4", "bank_time"])
    op.create_index("ix_p2p_incoming_received", "p2p_incoming", ["received_at"])
    op.create_table(
        "p2p_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("mode", sa.String(16), nullable=False, server_default="off"),
        sa.Column("allowlist_merchant_ids", pg.ARRAY(UUID), nullable=False, server_default="{}"),
        sa.Column("humo_bot_user_id", sa.BigInteger, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("id = 1", name="singleton"),
        sa.CheckConstraint("mode IN ('off','allowlist','all')", name="mode"),
    )
    op.execute("INSERT INTO p2p_settings (id, mode) VALUES (1, 'off')")


def downgrade() -> None:
    op.drop_table("p2p_settings")
    op.drop_table("p2p_incoming")
    op.drop_table("p2p_reservations")
    op.drop_table("p2p_cards")
