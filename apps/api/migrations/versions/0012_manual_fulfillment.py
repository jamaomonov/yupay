"""Manual fulfilment skeleton.

Two additive changes that together unlock the admin-driven fulfilment path:

1. Relax ``ck_sku_sourcing_rules_mode`` so ``"manual"`` is a valid routing
   mode alongside ``auto`` / ``force_inventory`` / ``force_supplier``.
2. Add ``fulfillment_tasks.admin_note`` (TEXT) + ``fulfillment_tasks.completed_by``
   (VARCHAR(64)) so admins can record context + identity when finishing a
   manual task without overloading the supplier-merged ``extra_metadata`` JSON.

Revision ID: 0012_manual_fulfillment
Revises: 0011_users_display_currency
Create Date: 2026-05-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_manual_fulfillment"
down_revision: str | None = "0011_users_display_currency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Relax the sourcing mode CHECK.
    op.drop_constraint(
        "ck_sku_sourcing_rules_mode", "sku_sourcing_rules", type_="check"
    )
    op.create_check_constraint(
        "ck_sku_sourcing_rules_mode",
        "sku_sourcing_rules",
        "mode IN ('auto','force_inventory','force_supplier','manual')",
    )

    # 2. Audit columns on fulfillment_tasks.
    op.add_column(
        "fulfillment_tasks",
        sa.Column("admin_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "fulfillment_tasks",
        sa.Column("completed_by", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fulfillment_tasks", "completed_by")
    op.drop_column("fulfillment_tasks", "admin_note")

    op.drop_constraint(
        "ck_sku_sourcing_rules_mode", "sku_sourcing_rules", type_="check"
    )
    op.create_check_constraint(
        "ck_sku_sourcing_rules_mode",
        "sku_sourcing_rules",
        "mode IN ('auto','force_inventory','force_supplier')",
    )
