"""p2p_reservations.order_id — a reservation may pay a storefront order (ADR-0097).

Revision ID: 0097_p2p_reservation_order
Revises: 0096_attempt_kind_reopen
Create Date: 2026-10-05

Sub-project 2 of the P2P design: the same exact-amount reservation that tops
up a reseller's deposit (``purpose='merchant_deposit'``, ``merchant_id`` set)
can now be the payment intent of a storefront order (``purpose='order'``,
``order_id`` set, ``merchant_id`` NULL). One pending reservation per order,
the way there is one per merchant. The purpose check from ``0093`` admitted
one value; this widens it by one. Raw SQL for the check because ``0093``
named it ``purpose`` under the metadata naming convention, so its stored
name is ``ck_p2p_reservations_purpose``; ``DROP IF EXISTS`` on both
spellings keeps this runnable whichever one a database carries.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0097_p2p_reservation_order"
down_revision: str | None = "0096_attempt_kind_reopen"
branch_labels: str | None = None
depends_on: str | None = None

_PURPOSE = "ck_p2p_reservations_purpose"


def _purpose_check(values: tuple[str, ...]) -> None:
    for name in (_PURPOSE, "purpose"):
        op.execute(f"ALTER TABLE p2p_reservations DROP CONSTRAINT IF EXISTS {name}")
    # Spelled out rather than ``repr``'d: a one-element tuple prints with a
    # trailing comma, which Postgres refuses — the downgrade hit exactly that.
    allowed = ", ".join(f"'{v}'" for v in values)
    op.execute(
        f"ALTER TABLE p2p_reservations ADD CONSTRAINT {_PURPOSE} CHECK (purpose IN ({allowed}))"
    )


def upgrade() -> None:
    op.add_column(
        "p2p_reservations",
        sa.Column(
            "order_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", name="fk_p2p_reservations_order_id_orders"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_p2p_reservations_one_pending_order",
        "p2p_reservations",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending' AND order_id IS NOT NULL"),
    )
    _purpose_check(("merchant_deposit", "order"))
    # The provider starts DISABLED. A missing state row reads as ``active``,
    # which would put «Перевод на карту» on every checkout the moment this
    # deploys — before the bot is connected and a card is on file. The owner
    # turns it on from the admin provider list once the go-live checklist is
    # done (docs/runbooks/p2p-deposit.md §10).
    op.execute(
        "INSERT INTO payment_provider_states (provider, state, changed_by, changed_at) "
        "VALUES ('p2p', 'disabled', NULL, CURRENT_TIMESTAMP) "
        "ON CONFLICT (provider) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM payment_provider_states WHERE provider = 'p2p'")
    op.execute("DELETE FROM p2p_reservations WHERE purpose = 'order'")
    _purpose_check(("merchant_deposit",))
    op.drop_index("uq_p2p_reservations_one_pending_order", table_name="p2p_reservations")
    op.drop_column("p2p_reservations", "order_id")
