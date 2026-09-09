"""Widen ``orders.source`` to the B2B surfaces: ``merchant_api``, ``merchant_panel``.

``ck_orders_source_known`` was written in 0046 against the only three surfaces
that existed — ``web``, ``miniapp``, ``bot`` — plus ``unknown`` for anything
that did not say. The merchant channel arrived with M2 and had no value to
claim, so every ``POST /merchant/v1/orders`` row landed in ``unknown`` and the
admin list rendered «—» for the one class of order whose origin is not in
doubt. An operator holding a reseller's dispute could not tell a B2B order from
a browser sale without opening it.

**Two values, one migration.** ``merchant_panel`` is M4's cabinet (the B2B
browser surface of the same account) and nothing sets it today; a second
revision for one string literal is waste, and the CHECK is the only thing that
would need changing. It is *allowed* here and *unreachable* until M4 writes it
— ``ORDER_SOURCES``, the accept list for the client-declared
``X-Yupay-Surface`` header, deliberately does not contain either value, so no
request can declare itself either one. A row carrying ``merchant_panel`` before
M4 ships means something wrote it that should not have.

**Why widening the vocabulary does not weaken the column.** ``source`` is
documented as client-declared and an operator's "where did this come from",
never an authorisation input. That stays true, and these two rows are the
*stronger* end of it: ``merchants.orders.place`` sets ``merchant_api``
server-side on a path that has already authenticated which merchant is calling,
so unlike a retail row it is not a claim the client made about itself. Nothing
is gated on it either way.

No column change: ``source`` is ``varchar(16)`` and ``merchant_panel``, the
longer of the two, is 14.

**The backfill is evidence, not a guess** — the same test 0046 applied when it
refused to assume ``web``. ``merchant_id IS NOT NULL`` is set by exactly one
code path, ``merchants.orders.place``, which is ``POST /merchant/v1/orders``;
the cabinet that would be the second one does not exist. So for every existing
merchant order the surface is *known*, not inferred, and leaving it in
``unknown`` would keep the admin saying «—» about the very orders this
milestone was opened over. Scoped to ``source = 'unknown'`` so it can never
overwrite a value some request actually declared.

**The constraint name is the double-prefixed one, on purpose.** 0046 created
it with the full explicit ``"ck_orders_source_known"``, and
``core.db.NAMING_CONVENTION`` re-templates even an explicitly named
CheckConstraint — so what is live in Postgres is
``ck_orders_ck_orders_source_known``. This revision addresses it the same way
0046 did, with the bare full name, which re-templates back into the live one
(the pattern 0018, 0056 and 0067 use). ``conv()`` would be wrong here: it
suppresses the templating, and the resulting ``ck_orders_source_known`` names
no constraint that exists.

Locking: ``DROP CONSTRAINT`` + ``ADD CONSTRAINT ... CHECK`` both take ACCESS
EXCLUSIVE on ``orders``, and the ADD scans the table to validate. The new
predicate is a strict superset of the old one, so no existing row can fail it
and the scan is the only cost — but it is still a scan under a lock that
conflicts with every checkout's ROW EXCLUSIVE, and ``deploy.yml`` runs
``alembic upgrade head`` while the old api containers are still serving. Same
three seconds of patience as 0069 and 0072: a contended deploy fails with
``lock_not_available`` and is retried in a quieter minute, rather than stalling
every INSERT queued behind it.

Revision ID: 0073_order_source_merchant
Revises: 0072_order_items_merchant_quote
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0073_order_source_merchant"
down_revision: str | None = "0072_order_items_merchant_quote"
branch_labels: str | None = None
depends_on: str | None = None

#: The vocabulary before this revision, and the one ``downgrade`` restores.
_OLD_SOURCES = ("web", "miniapp", "bot", "unknown")
#: The two the B2B channel claims. ``merchant_api`` is set by
#: ``merchants.orders.place``; ``merchant_panel`` is reserved for M4's cabinet.
_NEW_SOURCES = ("merchant_api", "merchant_panel")


def _check(values: tuple[str, ...]) -> str:
    return "source IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.execute("SET lock_timeout = '3s'")
    op.drop_constraint("ck_orders_source_known", "orders", type_="check")
    op.create_check_constraint(
        "ck_orders_source_known",
        "orders",
        _check(_OLD_SOURCES + _NEW_SOURCES),
    )
    # Scoped to the statements above: a plain ``SET`` lives for the rest of the
    # session, so without this every later revision in the same
    # ``upgrade head`` would inherit a patience it never asked for.
    op.execute("RESET lock_timeout")
    # Every merchant order placed before this revision came through the machine
    # API — there is no other writer of ``merchant_id`` — so this records what
    # happened rather than guessing at it. Runs after the CHECK is widened, or
    # it would be writing a value the constraint still refuses.
    op.execute(
        "UPDATE orders SET source = 'merchant_api' "
        "WHERE merchant_id IS NOT NULL AND source = 'unknown'"
    )


def downgrade() -> None:
    # Guard FIRST, in words, the way 0070's does. Narrowing the vocabulary back
    # is only possible while nothing uses the new half: Postgres would
    # otherwise refuse the ADD with ``check constraint ... is violated by some
    # row``, which names the constraint and never says that the rows in
    # question are merchant orders or what the operator is supposed to do with
    # them. The transaction aborts either way and no data is lost; this only
    # decides whether the message is readable.
    #
    # Deliberately NOT rewriting those rows to ``unknown``: that would make the
    # downgrade destroy the fact this revision exists to record, silently, on a
    # table whose whole purpose is financial history.
    #
    # Advisory, not race-proof — nothing locks the table between this count and
    # the DDL below. An order placed in that window is still caught, just with
    # the opaque error instead of this one.
    # Literal values rather than a bind parameter: they are this module's own
    # constants, and an ``IN`` over literals asks nothing of the driver's array
    # adaptation on a path that runs once, by hand, under pressure.
    stuck = (
        op.get_bind()
        .execute(sa.text(f"SELECT count(*) FROM orders WHERE {_check(_NEW_SOURCES)}"))
        .scalar_one()
    )
    if stuck:
        raise RuntimeError(
            f"Refusing to downgrade 0073: {stuck} order(s) record a B2B surface "
            f"({', '.join(_NEW_SOURCES)}), which the pre-0073 CHECK does not allow. "
            "Downgrading would either fail on the constraint or require rewriting "
            "those rows to 'unknown', destroying the only record that they came "
            "through the merchant channel. Restore from a backup taken before this "
            "revision instead."
        )
    op.execute("SET lock_timeout = '3s'")
    op.drop_constraint("ck_orders_source_known", "orders", type_="check")
    op.create_check_constraint("ck_orders_source_known", "orders", _check(_OLD_SOURCES))
    op.execute("RESET lock_timeout")
