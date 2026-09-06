"""Per-merchant idempotency scope on ``orders``: ``uq_orders_idem_merchant``.

0006 gave the two retail actor arms a partial UNIQUE each —
``uq_orders_idem_user`` on ``(user_id, idempotency_key)`` and
``uq_orders_idem_guest`` on ``(guest_email, idempotency_key)`` — so a repeated
``Idempotency-Key`` resolves in the database rather than in the read-then-write
inside ``orders.service._existing_idempotent_order``. 0066 added the third arm
(``merchant_id``) without its matching index. This adds it, in the same shape:
partial, UNIQUE, both columns NOT NULL in the predicate.

Scoped per merchant, not global. Resellers choose their own
``merchant_order_id`` values and cannot see each other's, so two merchants
colliding on one key is ordinary traffic — the same reasoning that makes the
user and guest scopes per-actor.

Naming: a plain string literal, not ``conv()``. The ``core.db`` warning about
re-templating applies to the ``ck`` template, which embeds
``%(constraint_name)s`` and therefore overwrites even an explicit name; the
``ix`` template that governs ``Index`` objects does not, so an explicitly named
index is left exactly as written. This index is also being *born* here rather
than referenced by a name some earlier migration already mangled — the
"birth of the name" test in ``core.db`` — which is why it needs no escape
hatch. 0006's two siblings and 0066's ``ix_orders_merchant_created`` are named
the same plain way and are live under exactly those names.

No backfill and no data risk: the index is partial on ``merchant_id IS NOT
NULL``, and no merchant order can exist yet — the service could not build one
until this revision's companion change widened ``Actor``.

Revision ID: 0069_orders_merchant_idempotency
Revises: 0068_catalog_b2b_flags
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0069_orders_merchant_idempotency"
down_revision: str | None = "0068_catalog_b2b_flags"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "uq_orders_idem_merchant",
        "orders",
        ["merchant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("merchant_id IS NOT NULL AND idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_orders_idem_merchant", table_name="orders")
