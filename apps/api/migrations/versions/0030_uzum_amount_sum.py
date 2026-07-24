"""Rename ``uzum_transactions.amount_tiyin`` to ``amount_sum``.

Uzum Bank's Merchant API charges in **sums** (major UZS units), not tiyin — its
``amount`` field is an ``int64`` count of sums, and UZS orders are already
rounded to whole sums at creation (``orders.service._round_to_payable``). The
column is renamed to reflect the real unit it stores; the value semantics are
whole sums going forward. This is a pure rename — the column type
(``BigInteger``) and nullability are unchanged, and the table is Uzum-only
(sandbox, not yet live), so no value back-fill is needed.

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
