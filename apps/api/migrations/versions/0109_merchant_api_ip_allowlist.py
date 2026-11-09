"""``merchants.api_ip_allowlist``: one IP allowlist per merchant, for every key (ADR-0103).

Until now each API key carried its own list, fixed at issue. The cabinet now edits one
list that applies to all of a merchant's keys, and ``auth`` reads only this column.

Backfill from the live keys, so no integrated merchant notices the switch:

- every live key unrestricted → NULL (no filter), as before;
- every live key restricted → the union of their entries — a merchant whose keys all
  carried the same list keeps exactly that list;
- some restricted, some not → NULL. Restricting would lock the open key out of
  addresses nobody recorded; leaving it open drops the filter on the restricted ones,
  which the HMAC/key check still guards. The cabinet shows the empty list and the
  merchant can fill it in.

``merchant_api_keys.ip_allowlist`` stays, unread, so a rollback to the previous image
enforces the per-key lists again. Dropping it is a later migration.

Revision ID: 0109_merchant_api_ip_allowlist
Revises: 0108_brand_variants
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0109_merchant_api_ip_allowlist"
down_revision: str | None = "0108_brand_variants"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "merchants",
        sa.Column("api_ip_allowlist", postgresql.ARRAY(postgresql.INET()), nullable=True),
    )
    op.execute(
        """
        UPDATE merchants m
           SET api_ip_allowlist = u.entries
          FROM (
                SELECT k.merchant_id,
                       array_agg(DISTINCT e.entry ORDER BY e.entry) AS entries
                  FROM merchant_api_keys k
                  CROSS JOIN LATERAL unnest(k.ip_allowlist) AS e(entry)
                 WHERE k.revoked_at IS NULL
                 GROUP BY k.merchant_id
               ) u
         WHERE u.merchant_id = m.id
           AND NOT EXISTS (
                SELECT 1 FROM merchant_api_keys o
                 WHERE o.merchant_id = m.id
                   AND o.revoked_at IS NULL
                   AND (o.ip_allowlist IS NULL OR cardinality(o.ip_allowlist) = 0)
               )
        """
    )


def downgrade() -> None:
    op.drop_column("merchants", "api_ip_allowlist")
