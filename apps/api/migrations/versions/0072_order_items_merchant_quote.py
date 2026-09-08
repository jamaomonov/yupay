"""Record the price a merchant quoted: ``order_items.merchant_expected_price_usd``.

Spec item 3b (``docs/superpowers/specs/2026-09-07-merchant-m3-requirements.md``)
asked for two records at order time: the **computed list price** and the
**merchant's own quote**. Only the second is missing, and this adds only the
second — see ADR-0071 for the check.

``POST /merchant/v1/orders`` carries an ``expected_price``. It decides whether
the order proceeds (``pricing.price_to_charge``, ±2 %) and then reaches exactly
one durable place: ``merchants.orders._request_digest`` SHA-256s it together
with the reseller's end-customer identifiers, and that digest is all the
``order.paid`` event holds. A digest answers "is this the same request?" and
nothing else, so a pilot arguing about a charge had no record of what they
sent, and nobody could measure how far merchants quote from our price.

**The other half of 3b needs no column, and adding one would be worse than
useless.** ``quote.price_for`` returns ``pricing.price_to_charge``'s result,
which is *our* current price or nothing (spec §8.4 as amended by the owner on
2026-09-07: ``expected_price`` is an accept/reject tolerance, never a bid).
``merchants.orders.place`` binds that one value to ``price`` and passes the
same object to ``unit_price_usd_override`` and to ``charge_deposit``. So
``order_items.unit_price_usd`` **is** the computed list price, already frozen;
a second column beside it would be filled from the same expression, and the
runbook's regression query — which earns its keep by *recomputing* the price
from ``order_items.cost_usdt`` and the SKU's markup — would become a
comparison of a value with itself.

No index, and the reason is **who reads it**, not whether anything filters on
it — the drift sweep in ``docs/runbooks/merchant-b2b.md`` filters on exactly
this column (``WHERE merchant_expected_price_usd IS NOT NULL``). What makes an
index wrong today is that no **code path** reads the column at all and nothing
orders by it; its only reader is an operator running a sweep by hand, for which
a sequential scan is fine and an index is write cost on every checkout.

And if that ever changes, the right index is not the one this migration would
have added. The predicate is ``IS NOT NULL``, so what a frequent reader would
want is a **partial** index restricted to the merchant lines, not a plain btree
over a price. Per AGENTS.md §10 it belongs in the same migration as the query
that needs it, which does not exist yet.

NULL means **not recorded**, and that covers two different things a reader must
not confuse: every retail line, which never had a quote, and any merchant line
placed before this revision. ``orders.merchant_id IS NOT NULL`` separates them.

Locking: ``ALTER TABLE … ADD COLUMN`` with no default and no volatile
expression is a catalogue write in Postgres 16 — it rewrites nothing — but it
still takes ACCESS EXCLUSIVE on ``order_items``, which conflicts with every
checkout's ROW EXCLUSIVE, and ``deploy.yml`` runs ``alembic upgrade head``
while the old api containers are still serving. Postgres queues lock requests
FIFO, so waiting behind one slow order transaction stalls every INSERT behind
it too. ``lock_timeout`` turns that production write stall into a deploy step
that fails with ``lock_not_available`` and is retried in a quieter minute —
the same reasoning, and the same three seconds, as 0069.

Revision ID: 0072_order_items_merchant_quote
Revises: 0071_merchant_webhooks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0072_order_items_merchant_quote"
down_revision: str | None = "0071_merchant_webhooks"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '3s'")
    op.add_column(
        "order_items",
        sa.Column("merchant_expected_price_usd", sa.Numeric(20, 6), nullable=True),
    )
    # Scoped to the statement above: a plain ``SET`` lives for the rest of the
    # session, so without this every later revision in the same
    # ``upgrade head`` would inherit a patience it never asked for.
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    # Dropping this column destroys the only record of what each merchant
    # quoted; there is no other copy (the ``order.paid`` digest is one-way).
    # That is the right behaviour for a downgrade — it is what "undo this
    # revision" means — and it is said out loud here because nothing else
    # would say it.
    op.drop_column("order_items", "merchant_expected_price_usd")
