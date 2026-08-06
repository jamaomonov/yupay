"""Indexes behind the admin order search (``GET /admin/orders?q=``).

The search has three shapes and each needs its own access path. A full UUID
already rides the primary key or ``ix_orders_user_created``; the two added here
cover the rest:

- ``ix_orders_id_prefix`` — ``id::text text_pattern_ops`` so a copied id
  fragment matches as a prefix instead of scanning the table. The default
  opclass cannot serve ``LIKE 'abc%'``, which is why the cast index is explicit.
- ``ix_orders_guest_email_trgm`` — a trigram GIN so a partial address from a
  support ticket is a real substring search. ``guest_email`` is CITEXT, so it is
  lowered and cast to text to match the trigram operator class.

Both are created concurrently-safe-by-default (plain CREATE INDEX): orders is
locked only briefly at this size, and Alembic runs inside a transaction where
CONCURRENTLY is not allowed.

Revision ID: 0039_orders_admin_search_indexes
Revises: 0038_payment_attempt_settle_kind
"""

from __future__ import annotations

from alembic import op

revision: str = "0039_orders_admin_search_indexes"
down_revision: str | None = "0038_payment_attempt_settle_kind"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX ix_orders_id_prefix ON orders ((id::text) text_pattern_ops)")
    op.execute(
        "CREATE INDEX ix_orders_guest_email_trgm ON orders "
        "USING gin (lower(guest_email::text) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_orders_guest_email_trgm")
    op.execute("DROP INDEX IF EXISTS ix_orders_id_prefix")
