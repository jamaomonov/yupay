"""``auth_sessions.kind = 'admin'``: the admin panel's sessions are their own kind.

Until now admin rights rode on the account: any session of a user holding the
``admin`` role — the mini app, the storefront — could call ``/admin/*``. A
session opened through the admin login is now ``kind='admin'``, its access
tokens carry ``adm``, and ``require_admin`` accepts nothing else (audit
2026-11-10). Existing rows are untouched: every live admin session predates
this and is ``user``, so admins sign in to the panel once more.

Revision ID: 0110_admin_sessions
Revises: 0109_merchant_api_ip_allowlist
"""

from __future__ import annotations

from alembic import op

revision: str = "0110_admin_sessions"
down_revision: str | None = "0109_merchant_api_ip_allowlist"
branch_labels = None
depends_on = None


# The names as the database holds them: 0001 passed already-prefixed names
# through the ``ck_%(table_name)s_%(constraint_name)s`` convention, so they
# carry the prefix twice. Raw SQL, so no convention can rename them again.
_KIND = "ck_auth_sessions_ck_auth_sessions_kind"
_SHAPE = "ck_auth_sessions_ck_auth_sessions_shape"


def _replace(kinds: str, owner_kinds: str) -> None:
    op.execute(f"ALTER TABLE auth_sessions DROP CONSTRAINT IF EXISTS {_KIND}")
    op.execute(f"ALTER TABLE auth_sessions DROP CONSTRAINT IF EXISTS {_SHAPE}")
    op.execute(f"ALTER TABLE auth_sessions ADD CONSTRAINT {_KIND} CHECK (kind IN ({kinds}))")
    op.execute(
        f"ALTER TABLE auth_sessions ADD CONSTRAINT {_SHAPE} CHECK ("
        f"(kind IN ({owner_kinds}) AND user_id IS NOT NULL AND refresh_token_hash IS NOT NULL) "
        "OR (kind = 'guest' AND user_id IS NULL AND guest_email IS NOT NULL))"
    )


def upgrade() -> None:
    _replace("'user', 'guest', 'admin'", "'user', 'admin'")


def downgrade() -> None:
    # Admin sessions cannot exist under the old constraint; end them.
    op.execute("DELETE FROM auth_sessions WHERE kind = 'admin'")
    _replace("'user', 'guest'", "'user'")
