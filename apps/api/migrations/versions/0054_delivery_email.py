"""Where an order's codes are actually sent.

Revision ID: 0054_delivery_email
Revises: 0053_order_item_cost
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import CITEXT

revision: str = "0054_delivery_email"
down_revision: str | None = "0053_order_item_cost"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deliberately NOT ``users.email``. That column is the login identity: it
    # carries ``uq_users_email_alive`` and three auth lookups resolve an
    # account by it. Letting a signed-in Telegram customer write an unverified
    # address into it would collide with a real account's uniqueness at best,
    # and at worst let them claim an address a password reset later targets.
    # This one is a mailing address and nothing else — not unique, never
    # looked up, never a credential.
    op.add_column("users", sa.Column("delivery_email", CITEXT(), nullable=True))
    # Per-order, because the buyer is asked at checkout and may want this one
    # order somewhere else. ``guest_email`` cannot serve: it is half of
    # ``ck_orders_actor_exclusive`` and must stay NULL on a signed-in order.
    op.add_column("orders", sa.Column("delivery_email", CITEXT(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "delivery_email")
    op.drop_column("users", "delivery_email")
