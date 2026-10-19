"""Widen ``orders.source`` to ``mobile``, the Expo app (ADR-0100).

The app sends ``X-Yupay-Surface: mobile``. Without this value the header would
normalise to ``unknown`` and an operator could not tell an app sale from an
order placed by an old client. Same shape as 0073: drop and re-add
``ck_orders_source_known`` with a strict superset of the old predicate, under
a 3-second lock timeout so a contended deploy fails fast instead of queueing
checkouts behind the validation scan. No backfill: no order came from the app
before this revision.

Revision ID: 0102_order_source_mobile
Revises: 0101_brand_regions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0102_order_source_mobile"
down_revision: str | None = "0101_brand_regions"
branch_labels: str | None = None
depends_on: str | None = None

_OLD_SOURCES = ("web", "miniapp", "bot", "unknown", "merchant_api", "merchant_panel")
_NEW_SOURCES = ("mobile",)


def _check(values: tuple[str, ...]) -> str:
    return "source IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.execute("SET lock_timeout = '3s'")
    op.drop_constraint("ck_orders_source_known", "orders", type_="check")
    op.create_check_constraint(
        "ck_orders_source_known", "orders", _check(_OLD_SOURCES + _NEW_SOURCES)
    )
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    # Refuse rather than rewrite app orders to ``unknown`` — see 0073's downgrade.
    stuck = (
        op.get_bind()
        .execute(sa.text(f"SELECT count(*) FROM orders WHERE {_check(_NEW_SOURCES)}"))
        .scalar_one()
    )
    if stuck:
        raise RuntimeError(
            f"Refusing to downgrade 0102: {stuck} order(s) came from the mobile app, "
            "which the pre-0102 CHECK does not allow. Restore from a backup instead."
        )
    op.execute("SET lock_timeout = '3s'")
    op.drop_constraint("ck_orders_source_known", "orders", type_="check")
    op.create_check_constraint("ck_orders_source_known", "orders", _check(_OLD_SOURCES))
    op.execute("RESET lock_timeout")
