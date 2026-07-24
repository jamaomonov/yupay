"""Rename ``uzum_transactions.amount_sum`` back to ``amount_tiyin``.

Undoes migration ``0030``. Uzum Bank's Merchant API sends the wire ``amount``
(on ``/create`` / ``/confirm`` / ``/reverse`` / ``/status`` and in the
checkout URL) in **tiyin** (minor units) — confirmed with Uzum's integration
engineer; only ``/check``'s ``data.amount.value`` is in sums. Migration
``0030`` briefly renamed the column to ``amount_sum`` on the mistaken belief the
whole integration was sum-denominated; this reverts that so the column matches
the ``UzumTransaction.amount_tiyin`` model again.

Kept as a forward-only step (rather than deleting ``0030``) so that
``alembic upgrade head`` converges **every** database to ``amount_tiyin``:
a DB already at ``0030`` applies only this step; a fresh or ``0029`` DB applies
``0030`` (→ ``amount_sum``) then ``0031`` (→ ``amount_tiyin``). The table is
Uzum-only and holds no live data (sandbox), so the round-trip rename is a pure
schema no-op on values.

Revision ID: 0031_uzum_amount_sum_to_tiyin
Revises: 0030_uzum_amount_sum
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0031_uzum_amount_sum_to_tiyin"
down_revision: str | None = "0030_uzum_amount_sum"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("uzum_transactions", "amount_sum", new_column_name="amount_tiyin")


def downgrade() -> None:
    op.alter_column("uzum_transactions", "amount_tiyin", new_column_name="amount_sum")
