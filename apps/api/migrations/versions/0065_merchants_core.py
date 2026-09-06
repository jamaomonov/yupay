"""Merchant B2B schema: merchants, their cabinet users, and their API keys.

Three tables, no changes to existing ones — the orders-side FK and the
deposit ledger accounts land in later migrations of this feature so this one
can ship on its own. See ``docs/superpowers/specs/2026-09-06-merchant-b2b-design.md``
§6.

``markup_adjustment_pp`` is dormant: no code reads it yet, it exists so a
later per-merchant pricing override (spec §8.3) is a data change, not a
schema change.

Revision ID: 0065_merchants_core
Revises: 0064_steam_gifts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0065_merchants_core"
down_revision: str | None = "0064_steam_gifts"
branch_labels: str | None = None
depends_on: str | None = None

_TS = sa.DateTime(timezone=True)
_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "merchants",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column("markup_adjustment_pp", sa.Numeric(5, 2), nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        # Bare suffix, not the full name: env.py passes our app's metadata as
        # ``target_metadata``, and alembic's ``op.create_table`` reuses its
        # naming convention — which, for CheckConstraint, interpolates a
        # given name as the ``constraint_name`` token rather than using it
        # verbatim. The full name here would land in the database as
        # ``ck_merchants_ck_merchants_status_known``.
        sa.CheckConstraint("status IN ('active', 'frozen')", name="status_known"),
    )

    op.create_table(
        "merchant_users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("email_confirmed_at", _TS, nullable=True),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'Asia/Tashkent'"),
        ),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
    )
    op.create_index("ix_merchant_users_merchant_id", "merchant_users", ["merchant_id"])

    op.create_table(
        "merchant_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_id", sa.String(length=48), nullable=False, unique=True),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False, server_default=sa.text("''")),
        sa.Column("ip_allowlist", postgresql.ARRAY(postgresql.INET()), nullable=True),
        sa.Column("last_used_at", _TS, nullable=True),
        sa.Column("revoked_at", _TS, nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
    )
    op.create_index("ix_merchant_api_keys_merchant_id", "merchant_api_keys", ["merchant_id"])


def downgrade() -> None:
    op.drop_table("merchant_api_keys")
    op.drop_table("merchant_users")
    op.drop_table("merchants")
