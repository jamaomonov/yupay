"""Cabinet sessions for merchant users, and the offer they accepted.

Revision ID: 0078_merchant_cabinet
Revises: 0077_blog_indexnow

``merchant_users`` has existed since M1 with an email, a password hash and a
confirmation stamp — and until now nothing created one and nothing logged one
in. The cabinet (spec §11) is what uses them, and it needs two things the
table cannot hold on its own.

**Sessions.** Modelled on ``affiliate_sessions``: the refresh token is stored
as a hash, never in the clear, and the access JWT carries the session id so a
revocation reaches tokens already minted. A separate table rather than a
column because a merchant operator may be signed in on more than one device
and signing one out must not sign out the others.

**The accepted offer.** Recorded on the *user*, not the merchant: a person
ticks a box, and which person and which version they ticked is the fact worth
keeping. Both columns are nullable — every merchant that exists today was
created by support and accepted nothing, and back-filling a consent nobody
gave is exactly the thing a consent record must not do.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0078_merchant_cabinet"
down_revision: str | None = "0077_blog_indexnow"
branch_labels: str | None = None
depends_on: str | None = None

_TS = sa.DateTime(timezone=True)
_NOW = sa.text("CURRENT_TIMESTAMP")
_UUID = postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    op.create_table(
        "merchant_sessions",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "merchant_user_id",
            _UUID,
            sa.ForeignKey("merchant_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The refresh token's SHA-256, like ``affiliate_sessions``: a database
        # dump must not be a set of live credentials.
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("revoked_at", _TS, nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
    )
    # Unique, not merely indexed: two sessions cannot share a refresh token,
    # and the lookup on rotation is by hash.
    op.create_index(
        "uq_merchant_sessions_token_hash",
        "merchant_sessions",
        ["token_hash"],
        unique=True,
    )
    # Every "sign me out everywhere" and every expiry sweep reads by user.
    op.create_index(
        "ix_merchant_sessions_user",
        "merchant_sessions",
        ["merchant_user_id"],
    )

    op.add_column(
        "merchant_users",
        sa.Column("offer_version", sa.String(32), nullable=True),
    )
    op.add_column(
        "merchant_users",
        sa.Column("offer_accepted_at", _TS, nullable=True),
    )
    # Either both or neither: a version with no timestamp cannot be evidence of
    # anything, and a timestamp with no version cannot say what was accepted.
    op.create_check_constraint(
        "ck_merchant_users_offer_complete",
        "merchant_users",
        "(offer_version IS NULL) = (offer_accepted_at IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_merchant_users_offer_complete", "merchant_users", type_="check")
    op.drop_column("merchant_users", "offer_accepted_at")
    op.drop_column("merchant_users", "offer_version")
    op.drop_index("ix_merchant_sessions_user", table_name="merchant_sessions")
    op.drop_index("uq_merchant_sessions_token_hash", table_name="merchant_sessions")
    op.drop_table("merchant_sessions")
