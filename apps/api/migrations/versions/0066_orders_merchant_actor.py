"""Orders grow a third actor arm: ``merchant_id``.

A B2B order belongs to a merchant the way retail orders belong to a user or a
guest. Nullable UUID FK to ``merchants`` (RESTRICT — merchant orders are
financial history; a merchant that has traded gets frozen, not deleted), a
partial index mirroring ``ix_orders_user_created``, and the actor CHECK widened
from XOR-of-two to exactly-one-of-three.

Naming repair rides along. 0006 wrote the CHECK's full name through the
metadata naming convention, which re-templates explicitly named
CheckConstraints (see the warning at ``core/db.py``), so every real database —
production included — holds it as ``ck_orders_ck_orders_actor_exclusive``. The
drop below targets that live name (``conv()`` keeps alembic from templating it
a third time) and the re-add passes the bare suffix so the new CHECK finally
lands as the clean ``ck_orders_actor_exclusive``.

Downgrade restores reality, not the ideal: the two-arm CHECK goes back under
its ugly double-prefixed name. It refuses — explicitly, before touching
anything — to run while any merchant order exists: with ``merchant_id``
dropped such rows would have zero actors, and the restored two-arm CHECK
could never be re-added over them anyway. There is no rollback past this
revision without first dealing with those orders (refund/cancel/migrate them
by hand — they are financial history, never deletable).

Revision ID: 0066_orders_merchant_actor
Revises: 0065_merchants_core
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import conv

revision: str = "0066_orders_merchant_actor"
down_revision: str | None = "0065_merchants_core"
branch_labels: str | None = None
depends_on: str | None = None

#: The name 0006 actually shipped (double prefix), live in every existing DB.
_LIVE_OLD_NAME = "ck_orders_ck_orders_actor_exclusive"

_THREE_ARM_CHECK = (
    "(CASE WHEN user_id IS NULL THEN 0 ELSE 1 END"
    " + CASE WHEN guest_email IS NULL THEN 0 ELSE 1 END"
    " + CASE WHEN merchant_id IS NULL THEN 0 ELSE 1 END) = 1"
)
_TWO_ARM_CHECK = "(user_id IS NULL) <> (guest_email IS NULL)"


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("merchant_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.create_foreign_key(
        "fk_orders_merchant_id_merchants",
        "orders",
        "merchants",
        ["merchant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_orders_merchant_created",
        "orders",
        ["merchant_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("merchant_id IS NOT NULL"),
    )
    # ``conv()`` marks the name as already-final: without it the naming
    # convention re-templates even here, and the DROP would look for
    # ``ck_orders_ck_orders_ck_orders_actor_exclusive``.
    op.drop_constraint(conv(_LIVE_OLD_NAME), "orders", type_="check")
    # Bare suffix: the convention supplies the ``ck_orders_`` prefix, so the
    # new CHECK lands under the clean ``ck_orders_actor_exclusive``.
    op.create_check_constraint("actor_exclusive", "orders", _THREE_ARM_CHECK)


def downgrade() -> None:
    # Guard FIRST, before anything destructive. Without it the operator only
    # finds out at the two-arm CHECK re-add — after drop_column, via a
    # constraint-violation error that names the old double-prefixed CHECK and
    # never mentions merchants. Fail up front, in words, instead.
    merchant_orders = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM orders WHERE merchant_id IS NOT NULL"))
        .scalar_one()
    )
    if merchant_orders:
        raise RuntimeError(
            f"Refusing to downgrade 0066: {merchant_orders} order(s) have merchant_id set. "
            "Dropping the column would leave them with no actor at all, and the restored "
            "two-arm actor CHECK could not be re-added over them anyway. Resolve those "
            "merchant orders first — they are financial history, not deletable; see the "
            "0066 migration docstring."
        )
    op.drop_constraint(conv("ck_orders_actor_exclusive"), "orders", type_="check")
    op.drop_index("ix_orders_merchant_created", table_name="orders")
    op.drop_constraint("fk_orders_merchant_id_merchants", "orders", type_="foreignkey")
    op.drop_column("orders", "merchant_id")
    # Reproduce what 0006 shipped, double prefix and all — a downgraded schema
    # must match the one 0065 leaves behind, not an ideal that never existed.
    # Errors here if merchant orders exist (they would have zero actors); that
    # refusal is the point.
    op.create_check_constraint(conv(_LIVE_OLD_NAME), "orders", _TWO_ARM_CHECK)
