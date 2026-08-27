"""Affiliate program: partners, codes, attribution, commission, payouts, sessions.

Six tables, no changes to existing ones — the order-side columns land in the
migration that carries the discount itself, so this one can ship on its own.

Two constraints do design work rather than validation.
``uq_affiliate_attributions_user`` makes "a buyer belongs to one partner,
forever" a database guarantee. ``uq_affiliate_commissions_order`` is the entire
idempotency story of the accrual sweep: overlapping ticks cannot pay twice.

The percent ranges are CHECKed because they guard our own margin. Production
margin on price is 14.0% at worst; break-even on that SKU including commission
is a discount of about 12.2%, so a code outside 3-10% is a data-entry mistake
that costs money, not a preference.

Revision ID: 0057_affiliate_program
Revises: 0056_wallet_partner_accounts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057_affiliate_program"
down_revision: str | None = "0056_wallet_partner_accounts"
branch_labels: str | None = None
depends_on: str | None = None

_TS = sa.DateTime(timezone=True)
_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "affiliate_partners",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("email", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("contact", sa.String(length=128), nullable=True),
        sa.Column("channel", sa.String(length=512), nullable=True),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("password_hash", sa.String(length=256), nullable=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("admin_note", sa.String(length=1024), nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("approved_at", _TS, nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'suspended', 'rejected')",
            name="ck_affiliate_partners_status",
        ),
    )

    op.create_table(
        "affiliate_codes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "partner_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("affiliate_partners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("commission_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.CheckConstraint(
            "discount_percent >= 3 AND discount_percent <= 10",
            name="ck_affiliate_codes_discount_range",
        ),
        sa.CheckConstraint(
            "commission_percent >= 1 AND commission_percent <= 2",
            name="ck_affiliate_codes_commission_range",
        ),
        sa.CheckConstraint("code = upper(code)", name="ck_affiliate_codes_upper"),
    )

    op.create_table(
        "affiliate_attributions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "partner_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("affiliate_partners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "code_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("affiliate_codes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "first_order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.UniqueConstraint("user_id", name="uq_affiliate_attributions_user"),
    )

    op.create_table(
        "affiliate_commissions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "partner_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("affiliate_partners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "code_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("affiliate_codes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("base_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("available_at", _TS, nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.UniqueConstraint("order_id", name="uq_affiliate_commissions_order"),
        sa.CheckConstraint(
            "status IN ('pending', 'available', 'paid', 'void')",
            name="ck_affiliate_commissions_status",
        ),
        sa.CheckConstraint("amount >= 0", name="ck_affiliate_commissions_amount_non_negative"),
    )
    op.create_index(
        "ix_affiliate_commissions_status_available",
        "affiliate_commissions",
        ["status", "available_at"],
    )
    op.create_index(
        "ix_affiliate_commissions_partner_created",
        "affiliate_commissions",
        ["partner_id", "created_at"],
    )

    op.create_table(
        "affiliate_payouts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "partner_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("affiliate_partners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("card_number", sa.String(length=32), nullable=False),
        sa.Column("card_holder", sa.String(length=128), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'requested'")
        ),
        sa.Column("admin_note", sa.String(length=1024), nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("processed_at", _TS, nullable=True),
        sa.CheckConstraint(
            "status IN ('requested', 'approved', 'rejected', 'paid')",
            name="ck_affiliate_payouts_status",
        ),
        sa.CheckConstraint("amount > 0", name="ck_affiliate_payouts_amount_positive"),
    )
    op.create_index(
        "ix_affiliate_payouts_status_created", "affiliate_payouts", ["status", "created_at"]
    )

    op.create_table(
        "affiliate_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "partner_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("affiliate_partners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False, unique=True),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("revoked_at", _TS, nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
    )
    op.create_index("ix_affiliate_sessions_partner", "affiliate_sessions", ["partner_id"])


def downgrade() -> None:
    op.drop_table("affiliate_sessions")
    op.drop_table("affiliate_payouts")
    op.drop_table("affiliate_commissions")
    op.drop_table("affiliate_attributions")
    op.drop_table("affiliate_codes")
    op.drop_table("affiliate_partners")
