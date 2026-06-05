"""Add password_hash + email_verified_at to users.

``password_hash`` enables email+password authentication alongside the existing
Telegram flow. ``email_verified_at`` records when the user confirmed their
address (``NULL`` = unverified).

One-live-account-per-email is already enforced by the pre-existing
``uq_users_email_alive`` unique index: ``email`` is a ``CITEXT`` column, so that
index is already case-insensitive and partial on
``email IS NOT NULL AND deleted_at IS NULL``. No additional email index is
needed here.

Revision ID: 0020_user_passwords
Revises: 0019_brand_maintenance
Create Date: 2026-06-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_user_passwords"
down_revision: str | None = "0019_brand_maintenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "password_hash")
