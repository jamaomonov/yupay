"""Create the ten Free Fire items NOVA sells that we don't, and route them to it.

NOVA's ``free_fire_cis`` category carries six Level Up Packages, three Evo
Access durations and a Newbie Bundle that G2B does not. They become new SKUs
of the existing ``free-fire`` brand, priced at cost x 1.10 (the owner's
decision, matching the 9-11 % the brand's existing SKUs already carry) — see
``docs/superpowers/specs/2026-09-17-nova-steam-and-free-fire-design.md`` §5.

Run inside the api container so it can reach both the database and NOVA:

    docker compose -f docker-compose.prod.yml exec -T api \\
        python - < scripts/seed/2026-09-18_free_fire_nova_only.py

It is a **dry run** like that, same shape as
``2026-09-17_nova_mappings.py``: it prints what it would write and saves
nothing. Read the table, then run it again to commit:

    docker compose -f docker-compose.prod.yml exec -T -e APPLY=1 api \\
        python - < scripts/seed/2026-09-18_free_fire_nova_only.py

**Two things this script exists to get right:**

1. The new ``free-fire-packs`` product must not disable the brand's player
   check. ``integrations.player_check.brand_check_field`` (ADR-0079) returns
   a check only when every active product of a brand agrees on its check
   config, so this script reads ``required_fields`` off ``free-fire-diamonds``
   in the same transaction and copies it verbatim — never retyped, because a
   retyped copy drifts.
2. These ten SKUs are NOVA-only. Auto sourcing skips reserve suppliers
   (``RESERVE_SUPPLIERS`` in ``integrations.models``), so a SKU whose only
   mapping is NOVA routes to the manual queue unless something sets
   ``force_supplier = nova`` — which this script does, in the same
   transaction as the mapping.

**Money guard.** ``price_usd = ceil(cost_usdt * 1.10, cents)``. The table
below is the expected result of that formula against NOVA's price on
2026-09-17; if the live catalogue still agrees with it (within 10 %) the
*live* cost is what gets written, but only once ceiling it still lands on
the same cent the table lists — a live cost that moved enough to change the
price it produces is stopped rather than silently written, exactly like a
cost that moved more than 10 %. Either failure is a catalogue change for a
human to look at, not a number to seed past.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Product, ProductTranslation, Sku
from yupay.modules.fulfillment.suppliers.nova_client import (
    NovaClient,
    NovaError,
    NovaUnavailableError,
)
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.sourcing.models import SkuSourcingRule

SUPPLIER_SLUG = "nova"
CATEGORY_ID = "free_fire_cis"
#: `updated_by` audit value written on every row this script touches.
UPDATED_BY = "seed:2026-09-18_free_fire_nova_only"

#: cost_usdt * MARKUP, ceiled to the cent, is price_usd.
MARKUP = Decimal("1.10")

#: Saved on every SKU so the hourly cost refresh (`integrations.price_refresh`)
#: keeps re-deriving price_usd at this margin as NOVA's cost moves, instead of
#: freezing the shelf price the day this script ran.
MARGIN_PERCENT = Decimal("10")

#: How far NOVA's live cost may drift from the table below before this script
#: refuses to write anything. A price that moved that far is a catalogue
#: change for a human to look at, not a number to seed past.
_MAX_DRIFT = Decimal("0.10")

#: The slug new_slug for the six Level Up Packages and the Newbie Bundle —
#: they need a product that does not exist yet ("Наборы" / "Packs" /
#: "Toʻplamlar"). Evo Access joins the existing `free-fire-membership`: it is
#: time-limited access, which is what that product already means.
PACKS_PRODUCT_SLUG = "free-fire-packs"
MEMBERSHIP_PRODUCT_SLUG = "free-fire-membership"
DIAMONDS_PRODUCT_SLUG = "free-fire-diamonds"


@dataclass(frozen=True)
class _NewSku:
    """One of the ten SKUs this script creates."""

    sku_code: str
    denomination: str
    #: "packs" -> `free-fire-packs`, "membership" -> `free-fire-membership`.
    product: str
    #: NOVA's `offer_id` in the `free_fire_cis` category.
    offer_id: str
    #: This script's own record of NOVA's cost on 2026-09-17, and the price it
    #: implies. Both are re-verified against the live catalogue in `main` —
    #: they are not written blind.
    expected_cost_usdt: Decimal
    expected_price_usd: Decimal


#: The ten rows from the spec's table (§5), in ladder order.
NEW_SKUS: tuple[_NewSku, ...] = (
    _NewSku(
        "freefire_cis-newbie-bundle",
        "Newbie Bundle",
        "packs",
        "newbie_bundle",
        Decimal("0.224400"),
        Decimal("0.25"),
    ),
    _NewSku(
        "freefire_cis-level-up-6",
        "Level Up Package 6",
        "packs",
        "level_up_package_6",
        Decimal("0.293148"),
        Decimal("0.33"),
    ),
    _NewSku(
        "freefire_cis-level-up-10",
        "Level Up Package 10",
        "packs",
        "level_up_package_10",
        Decimal("0.523362"),
        Decimal("0.58"),
    ),
    _NewSku(
        "freefire_cis-level-up-15",
        "Level Up Package 15",
        "packs",
        "level_up_package_15",
        Decimal("0.523362"),
        Decimal("0.58"),
    ),
    _NewSku(
        "freefire_cis-level-up-20",
        "Level Up Package 20",
        "packs",
        "level_up_package_20",
        Decimal("0.523362"),
        Decimal("0.58"),
    ),
    _NewSku(
        "freefire_cis-level-up-25",
        "Level Up Package 25",
        "packs",
        "level_up_package_25",
        Decimal("0.523362"),
        Decimal("0.58"),
    ),
    _NewSku(
        "freefire_cis-level-up-30",
        "Level Up Package 30",
        "packs",
        "level_up_package_30",
        Decimal("0.753678"),
        Decimal("0.83"),
    ),
    _NewSku(
        "freefire_cis-evo-access-3d",
        "Evo Access 3d",
        "membership",
        "evo_access_3d",
        Decimal("0.418710"),
        Decimal("0.47"),
    ),
    _NewSku(
        "freefire_cis-evo-access-7d",
        "Evo Access 7d",
        "membership",
        "evo_access_7d",
        Decimal("0.711858"),
        Decimal("0.79"),
    ),
    _NewSku(
        "freefire_cis-evo-access-30d",
        "Evo Access 30d",
        "membership",
        "evo_access_30d",
        Decimal("2.093550"),
        Decimal("2.31"),
    ),
)

#: Where the "packs" SKUs land in the new product's own ladder (0-indexed,
#: insertion order == the price-ascending order the table is already in).
#: Where the "membership" SKUs land in `free-fire-membership`'s ladder: after
#: whatever is there now, never renumbering it. Read from the database rather
#: than assumed — it was three when this was written, and a seed that hardcodes
#: today's count silently stacks two SKUs on one position the day somebody adds
#: a fourth. Nothing breaks (there is no uniqueness on `(product_id,
#: sort_order)`), it just quietly stops sorting the way the operator expects.


def _ceil_to_cent(amount: Decimal) -> Decimal:
    """cost * MARKUP, rounded UP to the cent — price never lands below cost * 1.10."""
    return (amount * MARKUP).quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def _self_check_price_table() -> None:
    """Every frozen cost in `NEW_SKUS` must ceil to its own listed price.

    Pure and network-free, so it runs before anything else in `main`: a typo
    in the constant above is a mistake in this script, not a supplier's
    price move, and it is cheaper to catch here than after a NOVA round trip.
    """
    for row in NEW_SKUS:
        computed = _ceil_to_cent(row.expected_cost_usdt)
        if computed != row.expected_price_usd:
            raise SystemExit(
                f"{row.sku_code}: table cost {row.expected_cost_usdt} x {MARKUP} ceils "
                f"to {computed}, not the table's own {row.expected_price_usd} — "
                "NEW_SKUS disagrees with itself, fix it before running"
            )


def _offers_by_id(offers: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Index NOVA's offers by `offer_id`. A **list** per id: an id two offers
    share is an ambiguity to report, not to resolve by picking the first —
    the one script whose output decides where a customer's money goes."""
    by_id: dict[str, list[dict[str, Any]]] = {}
    for offer in offers:
        offer_id = str(offer.get("offer_id") or "").strip()
        if offer_id:
            by_id.setdefault(offer_id, []).append(offer)
    return by_id


def _resolve_live_costs(offers: list[dict[str, Any]]) -> tuple[dict[str, Decimal], list[str]]:
    """NOVA's current cost for each of the ten `offer_id`s, or why it has none."""
    by_id = _offers_by_id(offers)
    costs: dict[str, Decimal] = {}
    problems: list[str] = []
    for row in NEW_SKUS:
        candidates = by_id.get(row.offer_id, [])
        if not candidates:
            problems.append(
                f"{row.sku_code}: offer_id {row.offer_id!r} not found in nova's "
                f"{CATEGORY_ID} offers"
            )
            continue
        if len(candidates) > 1:
            names = ", ".join(str(c.get("name")) for c in candidates)
            problems.append(
                f"{row.sku_code}: offer_id {row.offer_id!r} matches {len(candidates)} "
                f"nova offers ({names}) — their catalogue is ambiguous here"
            )
            continue
        raw_price = candidates[0].get("price_usd")
        try:
            costs[row.sku_code] = Decimal(str(raw_price))
        except (InvalidOperation, TypeError):
            problems.append(
                f"{row.sku_code}: offer {row.offer_id!r} has no readable price_usd ({raw_price!r})"
            )
    return costs, problems


def _drift_problems(costs: dict[str, Decimal]) -> list[str]:
    """Rows whose live cost moved more than `_MAX_DRIFT` from the table."""
    problems = []
    for row in NEW_SKUS:
        live = costs[row.sku_code]
        drift = abs(live - row.expected_cost_usdt) / row.expected_cost_usdt
        if drift > _MAX_DRIFT:
            pct = (drift * 100).quantize(Decimal("0.1"))
            problems.append(
                f"{row.sku_code}: nova's live cost {live} has moved {pct}% from the "
                f"table's {row.expected_cost_usdt} — a catalogue change to look at, "
                "not a number to seed past"
            )
    return problems


def _price_problems(costs: dict[str, Decimal]) -> list[str]:
    """Rows where the live cost, ceiled, would write a price the table disagrees with.

    Distinct from `_drift_problems`: a live cost can sit well inside the 10 %
    band and still cross a cent boundary. Either way this is a computation
    disagreeing with the table, and it is stopped rather than picked.
    """
    problems = []
    for row in NEW_SKUS:
        live = costs[row.sku_code]
        computed = _ceil_to_cent(live)
        if computed != row.expected_price_usd:
            problems.append(
                f"{row.sku_code}: live cost {live} x {MARKUP} ceils to {computed}, "
                f"not the table's {row.expected_price_usd} — stopping rather than "
                "picking one"
            )
    return problems


def _upsert_product_stmt(  # Any: an Insert whose generic parameters SQLAlchemy does not export.
    *, product_id: str, brand_id: str, required_fields: list[dict[str, Any]]
) -> Any:
    """The ``ON CONFLICT (slug) DO UPDATE`` for `free-fire-packs`.

    `sort_order` is set only on insert: re-running this script must not
    clobber an operator's later reordering of the product shelf.
    """
    return (
        pg_insert(Product)
        .values(
            id=product_id,
            slug=PACKS_PRODUCT_SLUG,
            brand_id=brand_id,
            kind="top_up",
            sort_order=2,
            active=True,
            required_fields=required_fields,
        )
        .on_conflict_do_update(
            index_elements=[Product.slug],
            set_={
                "brand_id": brand_id,
                "kind": "top_up",
                "active": True,
                "required_fields": required_fields,
            },
        )
        .returning(Product.id)
    )


def _upsert_translation_stmt(*, product_id: str, locale: str, name: str) -> Any:  # Any: see above.
    """The ``ON CONFLICT (product_id, locale) DO UPDATE`` for one product translation."""
    return (
        pg_insert(ProductTranslation)
        .values(product_id=product_id, locale=locale, name=name)
        .on_conflict_do_update(
            index_elements=[ProductTranslation.product_id, ProductTranslation.locale],
            set_={"name": name},
        )
    )


def _upsert_sku_stmt(  # Any: see `_upsert_product_stmt` above.
    *,
    sku_id: str,
    product_id: str,
    sku_code: str,
    denomination: str,
    cost_usdt: Decimal,
    price_usd: Decimal,
    sort_order: int,
) -> Any:
    """The ``ON CONFLICT (sku_code) DO UPDATE`` for one of the ten SKUs.

    `sort_order` is set only on insert, same reasoning as the product upsert.
    """
    return (
        pg_insert(Sku)
        .values(
            id=sku_id,
            product_id=product_id,
            sku_code=sku_code,
            denomination=denomination,
            price_usd=price_usd,
            cost_usdt=cost_usdt,
            margin_percent=MARGIN_PERCENT,
            sort_order=sort_order,
            active=True,
        )
        .on_conflict_do_update(
            index_elements=[Sku.sku_code],
            set_={
                "product_id": product_id,
                "denomination": denomination,
                "price_usd": price_usd,
                "cost_usdt": cost_usdt,
                "margin_percent": MARGIN_PERCENT,
                "active": True,
            },
        )
        .returning(Sku.id)
    )


def _upsert_mapping_stmt(*, sku_id: str, offer_id: str) -> Any:  # Any: see above.
    """The ``ON CONFLICT (sku_id, supplier_slug) DO UPDATE`` for one `nova` mapping."""
    return (
        pg_insert(SkuSupplierMapping)
        .values(
            sku_id=sku_id,
            supplier_slug=SUPPLIER_SLUG,
            kind="game",
            external_product_id=CATEGORY_ID,
            external_variant_id=offer_id,
            is_active=True,
            updated_by=UPDATED_BY,
        )
        .on_conflict_do_update(
            index_elements=[SkuSupplierMapping.sku_id, SkuSupplierMapping.supplier_slug],
            set_={
                "kind": "game",
                "external_product_id": CATEGORY_ID,
                "external_variant_id": offer_id,
                "is_active": True,
                "updated_by": UPDATED_BY,
            },
        )
    )


def _upsert_sourcing_rule_stmt(*, sku_id: str) -> Any:  # Any: see above.
    """The ``ON CONFLICT (sku_id) DO UPDATE`` that forces one SKU's sourcing onto NOVA.

    NOVA is a reserve supplier: auto sourcing never picks it, however old its
    mapping. Every one of these ten SKUs has NOVA as its *only* mapping, so
    without this row they would look sellable and land in a human's inbox on
    every order instead.
    """
    return (
        pg_insert(SkuSourcingRule)
        .values(
            sku_id=sku_id,
            mode="force_supplier",
            supplier_slug=SUPPLIER_SLUG,
            updated_by=UPDATED_BY,
        )
        .on_conflict_do_update(
            index_elements=[SkuSourcingRule.sku_id],
            set_={
                "mode": "force_supplier",
                "supplier_slug": SUPPLIER_SLUG,
                "updated_by": UPDATED_BY,
            },
        )
    )


async def _create_rows(
    db: AsyncSession, *, costs: dict[str, Decimal]
) -> list[tuple[_NewSku, Decimal, Decimal]]:
    """Upsert the product, its translations, the ten SKUs, their `nova`
    mappings and their sourcing rules. Returns each row's written
    (cost, price) for the printed table.

    Reads `free-fire-diamonds`'s `required_fields` from the database in the
    same transaction and copies it verbatim onto `free-fire-packs` — never
    retyped, because a retyped copy drifts (ADR-0079's trap).
    """
    required_fields = (
        await db.execute(
            select(Product.required_fields)
            .join(Brand)
            .where(Brand.slug == "free-fire", Product.slug == DIAMONDS_PRODUCT_SLUG)
        )
    ).scalar_one()

    membership = (
        await db.execute(select(Product).where(Product.slug == MEMBERSHIP_PRODUCT_SLUG))
    ).scalar_one()

    packs_id = (
        await db.execute(
            _upsert_product_stmt(
                product_id=new_id(),
                brand_id=membership.brand_id,
                required_fields=list(required_fields),
            )
        )
    ).scalar_one()
    for locale, name in (("ru", "Наборы"), ("en", "Packs"), ("uz", "Toʻplamlar")):
        await db.execute(_upsert_translation_stmt(product_id=packs_id, locale=locale, name=name))

    written: list[tuple[_NewSku, Decimal, Decimal]] = []
    # `NEW_SKUS` is already in ladder (price-ascending) order within each
    # product, so a running counter per product doubles as `sort_order`:
    # 0.. for the brand-new `free-fire-packs`, and one past whatever
    # `free-fire-membership` currently ends at (never renumbering it).
    membership_start = int(
        (
            await db.execute(
                select(func.coalesce(func.max(Sku.sort_order), -1) + 1).where(
                    Sku.product_id == membership.id
                )
            )
        ).scalar_one()
    )
    packs_seen = 0
    evo_seen = 0
    for row in NEW_SKUS:
        if row.product == "packs":
            product_id = packs_id
            sort_order = packs_seen
            packs_seen += 1
        else:
            product_id = membership.id
            sort_order = membership_start + evo_seen
            evo_seen += 1

        cost = costs[row.sku_code]
        price = _ceil_to_cent(cost)
        sku_id = (
            await db.execute(
                _upsert_sku_stmt(
                    sku_id=new_id(),
                    product_id=product_id,
                    sku_code=row.sku_code,
                    denomination=row.denomination,
                    cost_usdt=cost,
                    price_usd=price,
                    sort_order=sort_order,
                )
            )
        ).scalar_one()
        await db.execute(_upsert_mapping_stmt(sku_id=sku_id, offer_id=row.offer_id))
        await db.execute(_upsert_sourcing_rule_stmt(sku_id=sku_id))
        written.append((row, cost, price))

    return written


def _print_table(rows: list[tuple[_NewSku, Decimal, Decimal]]) -> None:
    print(f"\n{len(rows)} sku(s) written (or would be):")
    sku_w = max(len("sku_code"), *(len(r.sku_code) for r, _, _ in rows))
    denom_w = max(len("denomination"), *(len(r.denomination) for r, _, _ in rows))
    print(
        f"  {'sku_code'.ljust(sku_w)}  {'denomination'.ljust(denom_w)}  "
        f"{'offer_id':<22}{'cost_usdt':>10}  price_usd"
    )
    for row, cost, price in rows:
        print(
            f"  {row.sku_code.ljust(sku_w)}  {row.denomination.ljust(denom_w)}  "
            f"{row.offer_id:<22}{cost!s:>10}  {price}"
        )


async def main() -> None:
    """Verify the price table, fetch NOVA's live costs, refuse on drift or a
    disagreeing computation, then — only when told to — write the product,
    the ten SKUs, their `nova` mappings and their `force_supplier` rules.

    **A dry run by default**, same reasoning as ``2026-09-17_nova_mappings.py``:
    this writes `force_supplier` rules, and a rule moves the next customer's
    order. `APPLY=1` is the second step, after the printed table is read.
    """
    _self_check_price_table()

    apply = os.environ.get("APPLY", "").strip().lower() in {"1", "true", "yes"}
    settings = get_settings()
    if not settings.nova_api_key:
        raise SystemExit("no NOVA API key configured — set NOVA_API_KEY and retry")

    client = NovaClient(
        api_key=settings.nova_api_key,
        base_url=settings.nova_base_url,
        timeout_seconds=settings.nova_request_timeout_seconds,
    )

    try:
        body = await client.get_offers(CATEGORY_ID)
    except (NovaError, NovaUnavailableError) as exc:
        raise SystemExit(f"cannot reach NOVA: {exc}") from exc

    offers = [o for o in (body.get("offers") or []) if isinstance(o, dict)]
    costs, resolve_problems = _resolve_live_costs(offers)
    if resolve_problems:
        for p in resolve_problems:
            print(f"  {p}")
        raise SystemExit(f"{len(resolve_problems)} of the ten offer_ids did not resolve cleanly")

    problems = _drift_problems(costs) + _price_problems(costs)
    if problems:
        for p in problems:
            print(f"  {p}")
        raise SystemExit(f"refusing to write — {len(problems)} row(s) need a human")

    async with get_session_factory()() as session:
        written = await _create_rows(session, costs=costs)
        _print_table(written)

        if apply:
            await session.commit()
        else:
            await session.rollback()

    verb = "written" if apply else "would be written"
    print(
        f"\n{len(written)} sku(s) {verb}: `free-fire-packs` product + translations, "
        f"{len(written)} `nova` mapping(s), {len(written)} `force_supplier` rule(s)."
    )
    if not apply:
        print(
            "\nDRY RUN — nothing was saved. Read the table above, then re-run with"
            " APPLY=1 to commit."
        )


if __name__ == "__main__":
    asyncio.run(main())
