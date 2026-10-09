"""affiliate_clicks — one row per visitor per partner link per day.

Revision ID: 0099_affiliate_clicks
Revises: 0098_skins_csmarket_source
Create Date: 2026-10-09

Partner links (``yupay.uz/?ref=CODE``) were never counted: the only answer to
"how many clicks did partner X get" came from two weeks of proxy logs. The
storefront now reports a landing with a browser beacon; ``UNIQUE(code_id,
visitor_hash, day)`` makes every repeat a no-op. See ``affiliate.clicks``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0099_affiliate_clicks"
down_revision: str | None = "0098_skins_csmarket_source"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "affiliate_clicks",
        sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "code_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey(
                "affiliate_codes.id",
                name="fk_affiliate_clicks_code_id_affiliate_codes",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "partner_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey(
                "affiliate_partners.id",
                name="fk_affiliate_clicks_partner_id_affiliate_partners",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("visitor_hash", sa.CHAR(64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("landing_path", sa.String(255), nullable=False, server_default=sa.text("'/'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("code_id", "visitor_hash", "day", name="uq_affiliate_clicks_visit"),
    )
    op.create_index("ix_affiliate_clicks_partner_day", "affiliate_clicks", ["partner_id", "day"])


def downgrade() -> None:
    op.drop_index("ix_affiliate_clicks_partner_day", table_name="affiliate_clicks")
    op.drop_table("affiliate_clicks")
