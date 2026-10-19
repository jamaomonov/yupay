"""``users.signup_source``: where the account was opened — web, mini app or mobile app.

New accounts get it from the creating request: ``X-Yupay-Surface`` on the web and app
sign-in routes, and ``miniapp`` on the mini app's own initData route, which nothing else can
reach. Set once, never overwritten by a later sign-in from another surface.

**Backfill, best effort for rows that predate it.** Facts first, then the best signal left:

1. No Telegram link created with the account (within 5 s of it): the account was opened by
   email, Google or Steam, which only the website offered — ``web``. A fact.
2. Opened through Telegram, with orders: the surface of its first order (``web`` or
   ``miniapp``). Strong, not certain — someone can open the account in one place and buy in
   the other.
3. Opened through Telegram, no orders: ``miniapp`` when ``telegram_links.language_code`` is
   set (the Login Widget payload carries no language, so the last Telegram sign-in was the
   mini app's), else ``web``. The weakest of the three.

Only rows still ``unknown`` are touched, so a re-run never rewrites a value.

Locking: ADD COLUMN with a constant default is metadata-only on Postgres 16; the CHECK scans
``users`` (a few thousand rows) under the same 3-second patience as 0073.

Revision ID: 0103_user_signup_source
Revises: 0102_order_source_mobile
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0103_user_signup_source"
down_revision: str | None = "0102_order_source_mobile"
branch_labels: str | None = None
depends_on: str | None = None

_TELEGRAM_CREATED = """
    EXISTS (
        SELECT 1 FROM telegram_links t
        WHERE t.user_id = users.id
          AND t.created_at <= users.created_at + interval '5 seconds'
    )
"""


def upgrade() -> None:
    op.execute("SET lock_timeout = '3s'")
    op.add_column(
        "users",
        sa.Column(
            "signup_source", sa.String(16), nullable=False, server_default=sa.text("'unknown'")
        ),
    )
    op.create_check_constraint(
        "signup_source_known",
        "users",
        "signup_source IN ('web', 'miniapp', 'mobile', 'unknown')",
    )
    op.execute("RESET lock_timeout")

    op.execute(
        f"UPDATE users SET signup_source = 'web' "
        f"WHERE signup_source = 'unknown' AND NOT {_TELEGRAM_CREATED}"
    )
    op.execute(
        f"""
        UPDATE users SET signup_source = first.source
        FROM (
            SELECT DISTINCT ON (user_id) user_id, source
            FROM orders
            WHERE user_id IS NOT NULL AND source IN ('web', 'miniapp')
            ORDER BY user_id, created_at
        ) AS first
        WHERE first.user_id = users.id AND users.signup_source = 'unknown'
          AND {_TELEGRAM_CREATED}
        """
    )
    op.execute(
        f"""
        UPDATE users SET signup_source = CASE
            WHEN EXISTS (
                SELECT 1 FROM telegram_links t
                WHERE t.user_id = users.id AND t.language_code IS NOT NULL
            ) THEN 'miniapp' ELSE 'web' END
        WHERE signup_source = 'unknown' AND {_TELEGRAM_CREATED}
        """
    )


def downgrade() -> None:
    op.drop_constraint("signup_source_known", "users", type_="check")
    op.drop_column("users", "signup_source")
