"""Record which surface an order was placed from.

Nothing stored it. The only trace was indirect and partial: Click runs a
separate merchant service per surface, so a payment with provider
``click_miniapp`` implies the mini app — but Payme, Uzum and wallet orders
carry no such hint, and neither does an order that was never paid. In
production that left 11 of 98 orders attributable and the rest a guess.

``source`` is written at checkout from the ``X-Yupay-Surface`` header the
storefront and mini app send on every request. It is a client-declared
value: an operator-facing "where did this come from", not an authorisation
input, and nothing is gated on it.

Backfill is deliberately partial — ``miniapp`` where a ``click_miniapp``
payment proves it, ``unknown`` everywhere else. Guessing "web" for the
remainder would turn an absence of evidence into a claim.

Revision ID: 0046_order_source
Revises: 0045_attempt_repeat_collapse
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0046_order_source"
down_revision: str | None = "0045_attempt_repeat_collapse"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "source",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
    )
    op.create_check_constraint(
        "ck_orders_source_known",
        "orders",
        "source IN ('web', 'miniapp', 'bot', 'unknown')",
    )
    # The one surface the existing data can prove: Click's mini-app merchant
    # service is a different service_id, so the provider slug is evidence.
    op.execute(
        """
        UPDATE orders o
        SET source = 'miniapp'
        WHERE EXISTS (
            SELECT 1 FROM payments p
            WHERE p.order_id = o.id AND p.provider = 'click_miniapp'
        )
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_source_known", "orders", type_="check")
    op.drop_column("orders", "source")
