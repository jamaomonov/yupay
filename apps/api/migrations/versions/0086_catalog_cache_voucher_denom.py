"""``supplier_catalog_cache``: a voucher can have denominations too.

The kind CHECK allowed ``voucher``, ``game`` and ``game_denom``, which
encodes an assumption that was true when it was written and is not any
more: that a voucher is flat — one product, one price — while only a game
has a ladder under it.

Both of the suppliers we buy codes from disagree.

* **NOVA** sells gift cards as a category (``roblox_global``) holding nine
  cards, each with its own ``card_id``, price and stock
  (``GET /api/v2/giftcards/cards``). The mapping already stores the pair;
  the cache had nowhere to put the child.
* **G-Engine** sells them as a shop product (``9``, "Roblox Global")
  holding nine denominations, each with its own id, ``price`` and
  ``stock`` (``GET /shop/denominations/9``). ``catalog_sync_gengine``'s
  own docstring named this and left it: "``game_denom`` doesn't fit a shop
  denomination semantically".

It does not, and reusing it would have been the cheaper lie: the mapping
picker filters the cache by kind, so a gift card's ladder listed as
``game_denom`` would surface under "Игра у поставщика" and the voucher
step would stay empty — which is exactly the state an operator reported
("у g engine постоянно каталог не синхронизирован").

So ``voucher_denom`` joins the CHECK, under the double-prefixed name the
constraint actually shipped with — see ``_CHECK`` below. Nothing else
changes: the key already carries ``parent_external_id`` since 0084, and the
parent index already covers ``(supplier_slug, kind, parent_external_id)``.

No data is written here. The syncers fill it on their next pass, and an
operator can press the button rather than wait.

Revision ID: 0086_catalog_cache_voucher_denom
Revises: 0085_archive_a_brandless_post
"""

from __future__ import annotations

from alembic import op

revision: str = "0086_catalog_cache_voucher_denom"
down_revision: str | None = "0085_archive_a_brandless_post"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "supplier_catalog_cache"
#: The **literal live name**, double-prefixed. The model declares this CHECK
#: as ``name="ck_supplier_catalog_cache_kind"``, and the metadata naming
#: convention (``core/db.py``) re-templates even an explicitly named
#: CheckConstraint — so what actually shipped is the name below, exactly as
#: ``ck_orders_ck_orders_actor_exclusive`` did. Raw SQL is used here rather
#: than ``op.drop_constraint``/``op.create_check_constraint`` for the same
#: reason 0066 needed ``conv()``: those build their constraint object on the
#: same metadata and would prefix this once more on the way out.
_CHECK = "ck_supplier_catalog_cache_ck_supplier_catalog_cache_kind"


def upgrade() -> None:
    # A CHECK swap takes ACCESS EXCLUSIVE on a table the hourly sync writes.
    # Fail fast rather than queue behind it — the same patience 0084 set.
    op.execute("SET lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT {_CHECK}")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CHECK} "
        "CHECK (kind IN ('voucher','game','game_denom','voucher_denom'))"
    )
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    # Rows of the new kind would fail the narrower CHECK, so they go first.
    # They are cache, rebuilt by the next sync; nothing reads them on the
    # order path.
    op.execute(f"DELETE FROM {_TABLE} WHERE kind = 'voucher_denom'")
    op.execute("SET lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT {_CHECK}")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CHECK} "
        "CHECK (kind IN ('voucher','game','game_denom'))"
    )
    op.execute("RESET lock_timeout")
