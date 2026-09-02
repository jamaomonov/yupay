"""Steam identities, one table like telegram_links.

Steam's OpenID returns only a steamid64 — no email — so a Steam sign-in
account is identified by this link the way Telegram accounts are identified
by theirs.

Revision ID: 0063_steam_links
Revises: 0062_fulfillment_pending_index
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0063_steam_links"
down_revision: str | None = "0062_fulfillment_pending_index"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "steam_links",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("steam_id", sa.BigInteger(), nullable=False),
        sa.Column("persona_name", sa.String(255), nullable=True),
        sa.Column("avatar_url", sa.String(1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_steam_links_steam_id", "steam_links", ["steam_id"])
    op.create_index("ix_steam_links_user_id", "steam_links", ["user_id"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_steam_links_user_id", table_name="steam_links", if_exists=True)
    op.drop_table("steam_links")
