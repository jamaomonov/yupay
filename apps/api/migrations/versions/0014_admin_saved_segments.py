"""Saved-segments table for the admin SPA.

Per-admin bookmarks (path + params JSON) so an operator can store a working
filter and recall it from the sidebar. Cascades on the owning user — when an
admin row is deleted, their bookmarks go too.

Revision ID: 0014_admin_saved_segments
Revises: 0013_cancel_orphan_payments
Create Date: 2026-05-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_admin_saved_segments"
down_revision: str | None = "0013_cancel_orphan_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_saved_segments",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("path", sa.String(255), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "owner_user_id", "name", name="uq_admin_saved_segments_owner_name"
        ),
    )
    op.create_index(
        "ix_admin_saved_segments_owner",
        "admin_saved_segments",
        ["owner_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_admin_saved_segments_owner", table_name="admin_saved_segments")
    op.drop_table("admin_saved_segments")
