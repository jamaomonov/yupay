"""Indexes for the admin lists and the audit timeline, which sort by time.

Every index on this schema was designed for a *point* lookup — by order id, by
user, by task. Nothing served a bare ``ORDER BY created_at DESC``, which is what
every admin list and the merged audit feed actually do, on a 10- and 15-second
poll respectively. Verified with EXPLAIN on production: ``SELECT * FROM orders
ORDER BY created_at DESC LIMIT 50`` planned as ``Seq Scan -> Sort``.

At 500 rows that is free. At 1.8M — twelve months at the target volume — each
poll reads roughly 2GB and sorts it, and since ``work_mem`` is 4MB the sort
spills to disk every time. One open admin tab becomes a continuous disk-sort
loop. It starts to hurt around 100k rows, which is a few weeks of the traffic
the ad campaign is meant to produce.

The ``(created_at DESC, id DESC)`` shape is deliberate on the paginated lists:
``created_at`` defaults to ``CURRENT_TIMESTAMP``, which is *transaction* start,
so every row a single checkout writes shares one value. Sorting on it alone has
no defined order among them, and rows duplicate and vanish across pages under
OFFSET. The id tiebreak fixes a correctness bug, not only a speed one.

Two existing indexes are dropped as redundant:

- ``ix_fulfillment_attempts_task_id`` is ``(task_id, created_at)`` and
  ``ix_fulfillment_attempts_task_id_created_at`` is ``(task_id, created_at
  DESC)``. B-trees scan backwards, so the pair is pure write amplification on a
  table projected at ~10M rows.
- ``ix_deliveries_order_item_id`` duplicates the ``uq_deliveries_order_item``
  unique on the same single column.

Plain ``CREATE INDEX`` rather than ``CONCURRENTLY``, following 0039: Alembic
runs inside a transaction where CONCURRENTLY is not allowed, and at present
sizes the lock is momentary. Revisit if this ever has to be applied to a large
table.

Revision ID: 0055_admin_list_sort_indexes
Revises: 0054_delivery_email
"""

from __future__ import annotations

from alembic import op

revision: str = "0055_admin_list_sort_indexes"
down_revision: str | None = "0054_delivery_email"
branch_labels: str | None = None
depends_on: str | None = None

#: ``(table, index name, columns)``. Each entry is backed by a query that runs
#: on a timer, not by a guess about what might one day be useful.
_INDEXES: tuple[tuple[str, str, str], ...] = (
    # Admin orders list + its status filter (orders/service.list_orders_admin).
    ("orders", "ix_orders_created_id", "created_at DESC, id DESC"),
    ("orders", "ix_orders_status_created", "status, created_at DESC, id DESC"),
    # Admin payments list, and the provider breakdown in analytics.
    ("payments", "ix_payments_created_id", "created_at DESC, id DESC"),
    ("payments", "ix_payments_status_created", "status, created_at DESC"),
    ("payments", "ix_payments_provider_created", "provider, created_at DESC"),
    # The audit timeline fans out over five sources and merges them in Python;
    # each one had only a parent-id-leading composite, unusable for a global
    # feed. These are the five, and they are the fastest-growing tables here.
    ("order_events", "ix_order_events_created_id", "created_at DESC, id DESC"),
    ("payment_attempts", "ix_payment_attempts_created", "created_at DESC"),
    ("payment_webhooks", "ix_payment_webhooks_received", "received_at DESC"),
    ("fulfillment_attempts", "ix_fulfillment_attempts_created", "created_at DESC"),
    ("wallet_transactions", "ix_wallet_transactions_created", "created_at DESC"),
    # Admin reviews feed (reviews/service.admin_list).
    ("reviews", "ix_reviews_created_id", "created_at DESC, id DESC"),
    # The three reconcile sweeps page through tasks by supplier every 60s;
    # `supplier` was unindexed and applied as a post-filter.
    (
        "fulfillment_tasks",
        "ix_fulfillment_tasks_supplier_status_created",
        "supplier, status, created_at, id",
    ),
)

_REDUNDANT: tuple[str, ...] = (
    "ix_fulfillment_attempts_task_id",
    "ix_deliveries_order_item_id",
)


def upgrade() -> None:
    for table, name, columns in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})")
    for name in _REDUNDANT:
        op.execute(f"DROP INDEX IF EXISTS {name}")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fulfillment_attempts_task_id "
        "ON fulfillment_attempts (task_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_deliveries_order_item_id ON deliveries (order_item_id)"
    )
    for _table, name, _columns in reversed(_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
