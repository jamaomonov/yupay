"""Partial index for the fulfilment queue's claim query.

Task 2's claim query and the worker's poll tick both select from
``fulfillment_tasks`` filtered on ``status = 'pending'`` ordered by
``created_at`` — §10 says the index lands with the query that needs it,
not after, so it ships here alongside the flag rather than waiting for
the consumer.

A tiny partial index: with ``fulfilment_async`` off (the default) the
``pending`` set stays ~empty — tasks are executed synchronously and land
``succeeded``/``failed`` within the same transaction — so this costs
next to nothing until the flag is flipped.

Revision ID: 0062_fulfillment_pending_index
Revises: 0061_auto_refund_sweep_indexes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0062_fulfillment_pending_index"
down_revision: str | None = "0061_auto_refund_sweep_indexes"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "ix_fulfillment_tasks_pending",
        "fulfillment_tasks",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_fulfillment_tasks_pending", "fulfillment_tasks")
