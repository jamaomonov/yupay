"""``supplier_catalog_cache``: one row per game's denomination, not per id.

The primary key was ``(supplier_slug, kind, external_id)``, which says a
denomination id is unique across a supplier's whole catalogue. It is not.
NOVA calls the 55-diamond pack ``55_diamonds`` in Magic Chess Go Go (RU) and
in Mobile Legends (RU) alike; G-Engine numbers denominations per service and
reuses the numbers. So two games sharing an id shared a *row*, and every
sync overwrote the other game's ``parent_external_id`` with its own.

Measured on production 2026-09-19 before this ran: NOVA returned 17 offers
for ``magic_chess_gogo_ru`` and the cache held 9 of them. The other eight —
55, 165, 275, 565, 1155, 1765, 2975 and 6000 Diamonds — were sitting under
``mobile_legends_ru``, which had synced later and taken them. An operator
mapping Magic Chess RU simply could not see those denominations in the
picker, and nothing anywhere said why.

``parent_external_id`` therefore joins the key. It becomes ``NOT NULL``
defaulting to ``''`` rather than staying nullable, because a key column
cannot be ``NULL`` and because the admin already treats the empty string as
"no parent" when it asks (``DenomCatalogPicker`` sends
``parent_external_id: gameExternalId ?? ""``). Flat ``voucher``/``game`` rows
keep exactly one row each, as before.

Key order is ``(supplier_slug, kind, external_id, parent_external_id)`` and
not parent-first on purpose: ``cost_lookup`` reads a voucher by
``(supplier_slug, kind, external_id)``, which stays an exact index prefix.
Listing one game's denominations keeps using
``ix_supplier_catalog_cache_parent``, which is why no index is touched here.

**No data repair is needed and none is attempted.** Rows currently parked
under the wrong game are corrected by the syncers themselves: since
``service.prune_catalog_denoms`` shipped, a game's sync deletes rows carrying
its parent that it no longer lists, and the rightful game re-creates them on
its own pass. One hourly sweep covers every mapped game. Deleting the
``game_denom`` rows here instead would empty the mapping picker for up to an
hour and buy nothing.

The table is a cache: 2129 rows and 1.5 MB on production, off the order path.
The key swap rewrites its index in an instant, but still takes ACCESS
EXCLUSIVE, so it is bounded by ``lock_timeout`` the same way 0069, 0072, 0073
and 0083 bound theirs.

Revision ID: 0084_catalog_cache_key_per_game
Revises: 0083_widen_photo_url
"""

from __future__ import annotations

from alembic import op

revision: str = "0084_catalog_cache_key_per_game"
down_revision: str | None = "0083_widen_photo_url"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "supplier_catalog_cache"
_PK = "pk_supplier_catalog_cache"


def upgrade() -> None:
    # Before the column can join the key. Every flat voucher/game row is one
    # of these; no game_denom row has ever been written without a parent.
    op.execute(f"UPDATE {_TABLE} SET parent_external_id = '' WHERE parent_external_id IS NULL")
    op.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN parent_external_id SET DEFAULT ''")
    op.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN parent_external_id SET NOT NULL")

    # Fail fast rather than queue: see the docstring. A cache table nobody
    # reads on the order path is still a table a sync job may hold.
    op.execute("SET lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT {_PK}")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_PK} "
        "PRIMARY KEY (supplier_slug, kind, external_id, parent_external_id)"
    )
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    # Narrowing the key can genuinely fail, and that is not a bug in this
    # function: once two games hold the same denomination id — which is the
    # whole point of the upgrade — no three-column key covers them. Whoever
    # reverts this has to decide which row survives, so the delete below is
    # deliberate rather than incidental: it keeps the lowest-sorting parent
    # per id and drops the rest, exactly the collision the old key forced.
    op.execute(
        f"""
        DELETE FROM {_TABLE} a USING {_TABLE} b
        WHERE a.supplier_slug = b.supplier_slug
          AND a.kind = b.kind
          AND a.external_id = b.external_id
          AND a.parent_external_id > b.parent_external_id
        """
    )
    op.execute("SET lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT {_PK}")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_PK} PRIMARY KEY (supplier_slug, kind, external_id)"
    )
    op.execute("RESET lock_timeout")
    op.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN parent_external_id DROP NOT NULL")
    op.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN parent_external_id DROP DEFAULT")
    op.execute(f"UPDATE {_TABLE} SET parent_external_id = NULL WHERE parent_external_id = ''")
