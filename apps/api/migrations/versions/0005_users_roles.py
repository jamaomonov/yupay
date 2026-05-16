"""Add ``users.roles`` for admin/operator/finance role-based access (ADR-0010).

Revision ID: 0005_users_roles
Revises: 0004_catalog_brands
Create Date: 2026-05-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_users_roles"
down_revision: str | None = "0004_catalog_brands"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "roles",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    # Fast filter "all admins" — used by admin listings and audit reports.
    op.create_index(
        "ix_users_roles_admin",
        "users",
        ["roles"],
        postgresql_using="gin",
        postgresql_ops={"roles": "jsonb_path_ops"},
        postgresql_where=sa.text("roles ? 'admin'"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_roles_admin", table_name="users")
    op.drop_column("users", "roles")
