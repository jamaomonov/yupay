"""Partial indexes for the auto-refund sweep's selection query (ADR-0063).

§10: the index lands with the query that needs it. ``orders.risk.
auto_refund_expired_holds`` runs every 15 minutes and its selection query
does two lookups against ``order_events`` that neither existing index
(``ix_order_events_order_created`` is order-scoped; ``ix_order_events_created_id``
from 0055 backs the global, unfiltered admin audit feed) serves well, and
the table is append-only and grows unbounded — every hold, every release,
every refund attempt writes a row that never leaves.

Two indexes, one per lookup, both partial on ``kind`` so neither carries the
weight of every other event kind ever written:

- ``ix_order_events_held`` backs ``WHERE kind = 'order.held_for_review' AND
  created_at <= :cutoff`` — the deadline check. Indexed on ``created_at``
  alone (not also ``order_id``) because the predicate that actually narrows
  the scan is the time range; ``order_id`` is a heap fetch either way once
  Postgres has the matching rows.
- ``ix_order_events_auto_refund_escalated`` backs ``WHERE kind =
  'order.auto_refund_escalated'`` with **no** time predicate — the
  selection query's exclusion list (an order already escalated once must
  never be re-selected, see ``_escalate_auto_refund``). Indexed on
  ``order_id`` instead of ``created_at``: this lookup is a pure membership
  check ("has this order already been escalated, ever"), not a range scan,
  so the useful key is the column the outer query joins/excludes on, not
  time.

Revision ID: 0061_auto_refund_sweep_indexes
Revises: 0060_evidence_ip_country
"""

from __future__ import annotations

from alembic import op

revision: str = "0061_auto_refund_sweep_indexes"
down_revision: str | None = "0060_evidence_ip_country"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_events_held ON order_events (created_at) "
        "WHERE kind = 'order.held_for_review'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_events_auto_refund_escalated "
        "ON order_events (order_id) WHERE kind = 'order.auto_refund_escalated'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_order_events_auto_refund_escalated")
    op.execute("DROP INDEX IF EXISTS ix_order_events_held")
