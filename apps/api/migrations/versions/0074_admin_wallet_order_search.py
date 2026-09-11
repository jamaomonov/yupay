"""Indexes behind admin user-wallet totals and the expanded order search.

``GET /admin/users`` now aggregates every ``user_wallet`` account (liability
tiles + per-row balances + ``sort=wallet_*``). The unique on
``(owner_type, owner_id, kind, currency)`` leads with owner, so a
``WHERE kind = 'user_wallet'`` scan could not use it. The partial index
covers that filter.

``GET /admin/orders?q=`` grew three substring branches — owner name/email,
catalog brand/product name, merchant title. Each is spelled ``lower(col)
LIKE '%term%'`` so a trigram GIN of the same expression is the access path.
``ILIKE`` is deliberately not used: see migration 0039 and
``test_admin_search_indexable.py``.

Revision ID: 0074_admin_wallet_order_search
Revises: 0073_order_source_merchant
"""

from __future__ import annotations

from alembic import op

revision: str = "0074_admin_wallet_order_search"
down_revision: str | None = "0073_order_source_merchant"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wallet_accounts_user_wallet "
        "ON wallet_accounts (owner_id, currency) "
        "WHERE kind = 'user_wallet' AND owner_type = 'user'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_display_name_trgm "
        "ON users USING gin (lower(display_name) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_email_trgm "
        "ON users USING gin (lower(email::text) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_merchants_title_trgm "
        "ON merchants USING gin (lower(title) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_product_translations_name_trgm "
        "ON product_translations USING gin (lower(name) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_brand_translations_name_trgm "
        "ON brand_translations USING gin (lower(name) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_brand_translations_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_product_translations_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_merchants_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_users_email_trgm")
    op.execute("DROP INDEX IF EXISTS ix_users_display_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_wallet_accounts_user_wallet")
