"""Backfill: cancel pending payments whose order has already terminated.

History: ``_expire_order_inline`` and ``cancel_order_admin`` used to only flip the
order. Pending / requires_action payments on a terminated order were left untouched
and showed up in ``/admin/payments/triage`` as "stuck" indefinitely. The
cascade-cancel fix landed alongside this migration; the migration cleans up the
backlog the bug left behind.

Idempotent: re-running is a no-op once the rows are closed. Audit rows are inserted
only when a payment row actually flips.

Revision ID: 0013_cancel_orphan_payments
Revises: 0012_manual_fulfillment
Create Date: 2026-05-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013_cancel_orphan_payments"
down_revision: str | None = "0012_manual_fulfillment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_BACKFILL_PAYLOAD = (
    '{"trigger": "order_terminated", "reason": "backfill_0013", "actor": "system:backfill"}'
)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Audit row per affected payment — insert before the UPDATE so the
    #    selector still matches the original pending/requires_action set.
    bind.exec_driver_sql(
        f"""
        INSERT INTO payment_attempts (id, payment_id, kind, status, payload)
        SELECT gen_random_uuid(), p.id, 'cancel', 'ok', '{_BACKFILL_PAYLOAD}'::jsonb
        FROM payments p
        JOIN orders o ON o.id = p.order_id
        WHERE o.status IN ('expired', 'cancelled')
          AND p.status IN ('pending', 'requires_action');
        """
    )

    # 2. Flip the orphan payments themselves.
    bind.exec_driver_sql(
        """
        UPDATE payments AS p
        SET status = 'cancelled',
            updated_at = CURRENT_TIMESTAMP
        FROM orders AS o
        WHERE o.id = p.order_id
          AND o.status IN ('expired', 'cancelled')
          AND p.status IN ('pending', 'requires_action');
        """
    )


def downgrade() -> None:
    # Reversing a cancellation back to ``pending`` would re-open intents the
    # customer / provider already abandoned — we'd rather not.
    raise NotImplementedError(
        "0013 is a one-way data-quality migration; restore from backup instead."
    )
