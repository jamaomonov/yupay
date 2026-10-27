"""``brands.maintenance_redirect_id``: where a brand under maintenance sends its buyers.

A brand in maintenance keeps its page (and its search ranking) but takes no orders.
When the same goods can be bought elsewhere on the storefront, the page should say so
and link there instead of leaving the buyer at a dead end. First case (2026-10-27):
Standoff 2 promo codes paused while G-Engine is down, pointing at Standoff 2 Gold by
player id.

Shown only while ``maintenance`` is on; NULL means no redirect. A brand never points
at itself; deleting the target clears the link.

Revision ID: 0107_brand_maintenance_redirect
Revises: 0106_sku_notice
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0107_brand_maintenance_redirect"
down_revision: str | None = "0106_sku_notice"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "brands",
        sa.Column(
            "maintenance_redirect_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("brands.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Bare suffix: the naming convention adds the ``ck_brands_`` prefix (core/db.py).
    op.create_check_constraint(
        "maintenance_redirect_not_self",
        "brands",
        "maintenance_redirect_id IS NULL OR maintenance_redirect_id <> id",
    )


def downgrade() -> None:
    op.drop_constraint("ck_brands_maintenance_redirect_not_self", "brands", type_="check")
    op.drop_column("brands", "maintenance_redirect_id")
