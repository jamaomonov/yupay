"""Rename ``uzum_transactions.amount_tiyin`` to ``amount_sum``.

.. warning::

   This rename was a **mistake** and is immediately undone by migration
   ``0031`` (which renames the column back to ``amount_tiyin``). Uzum Bank's
   Merchant API sends the ``amount`` field in **tiyin** (minor units) on the
   wire; only ``/check``'s ``data.amount.value`` is in sums. The column is kept
   in this (temporary) chain purely so that a database already stamped at this
   revision can still locate it and roll forward to ``0031`` — do **not** delete
   this file, or such a database would fail ``alembic upgrade head`` with
   "Can't locate revision 0030_uzum_amount_sum".

Revision ID: 0030_uzum_amount_sum
Revises: 0029_click_transactions
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0030_uzum_amount_sum"
down_revision: str | None = "0029_click_transactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("uzum_transactions", "amount_tiyin", new_column_name="amount_sum")


def downgrade() -> None:
    op.alter_column("uzum_transactions", "amount_sum", new_column_name="amount_tiyin")
