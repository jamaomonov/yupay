"""Let one attempt row stand for a run of identical status polls.

``process_webhook_update`` records an attempt per poll, and the poller runs
once a minute for as long as a supplier order stays open. One production task
accumulated 1641 rows that way — 1640 of them the identical
``status_check / ok / {"outcome": "in_progress"}`` — for a single delivery
that eventually succeeded.

Those rows carry no information the first one does not, beyond "we were still
checking at T". ``repeat_count`` and ``last_seen_at`` carry exactly that, so a
run collapses to one row that says when it started, when it was last observed,
and how many times. The write path (``_record_attempt``) folds a repeat into
the previous row instead of inserting.

Nothing is dropped here: existing rows keep ``repeat_count = 1`` and this
migration touches no data. Collapsing the history that already accumulated is
a separate, reviewable step —
``scripts/seed/2026-08-16_collapse_attempt_runs.sql``.

Revision ID: 0045_attempt_repeat_collapse
Revises: 0044_order_item_rate_snapshot
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0045_attempt_repeat_collapse"
down_revision: str | None = "0044_order_item_rate_snapshot"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "fulfillment_attempts",
        sa.Column("repeat_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    # NULL means "observed once", i.e. `created_at` is also the last sighting.
    # Cheaper to read than back-filling every row with a copy of created_at.
    op.add_column(
        "fulfillment_attempts",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_fulfillment_attempts_repeat_positive",
        "fulfillment_attempts",
        "repeat_count >= 1",
    )
    # The write path looks up "the newest attempt of this task" on every poll;
    # without this it is a scan of the task's whole log, which is precisely the
    # thing that grows.
    op.create_index(
        "ix_fulfillment_attempts_task_id_created_at",
        "fulfillment_attempts",
        ["task_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_fulfillment_attempts_task_id_created_at", table_name="fulfillment_attempts")
    op.drop_constraint(
        "ck_fulfillment_attempts_repeat_positive", "fulfillment_attempts", type_="check"
    )
    op.drop_column("fulfillment_attempts", "last_seen_at")
    op.drop_column("fulfillment_attempts", "repeat_count")
