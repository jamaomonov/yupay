"""Account suspension (ADR-0045).

``banned_at`` is a timestamp rather than a boolean because "since when" is the
first question asked when a customer challenges a suspension, and ``banned_by``
because cutting off a paying customer should never be an anonymous act. The
self-referential FK is ``SET NULL``: the ban record must outlive the admin
account that created it.

``ix_users_banned_at`` is partial — the admin list filters for banned accounts,
which are by design a tiny minority of rows, so indexing only the non-null ones
keeps it small.

Revision ID: 0041_user_ban
Revises: 0040_order_evidence
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041_user_ban"
down_revision: str | None = "0040_order_evidence"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("ban_reason", sa.String(length=500), nullable=True))
    op.add_column("users", sa.Column("banned_by", postgresql.UUID(as_uuid=False), nullable=True))
    op.create_foreign_key(
        "fk_users_banned_by_users",
        "users",
        "users",
        ["banned_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_users_banned_at",
        "users",
        ["banned_at"],
        postgresql_where=sa.text("banned_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_banned_at", table_name="users")
    op.drop_constraint("fk_users_banned_by_users", "users", type_="foreignkey")
    op.drop_column("users", "banned_by")
    op.drop_column("users", "ban_reason")
    op.drop_column("users", "banned_at")
