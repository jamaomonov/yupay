"""Match our SKUs to NOVA offers and write `nova` supplier mappings.

Run inside the api container so it can reach both the database and NOVA:

    docker compose -f docker-compose.prod.yml exec -T api \
        python - < scripts/seed/2026-09-17_nova_mappings.py

It matches on the denomination number only — `Sku.units` when set, otherwise
the leading integer of `Sku.denomination` or `sku_code` — and writes a mapping
only on an exact match. Everything it could not match is printed for an
operator to finish in the admin: guessing which of "275 Diamonds" and "275
Diamonds + Bonus" a SKU meant is not a thing a script should do with money.

Mappings are written ACTIVE. That is safe because sourcing picks the oldest
active mapping (see `sourcing.service._resolve_auto`), so an order keeps going
to the incumbent supplier until somebody sets `force_supplier = nova`.

`pubg_mobile_auto` below is one of NOVA's four speed tiers for PUBG Mobile
(`_auto`, `_fast`, `_manual`, `_reserve` — same game, different fulfilment
speed and price); this script picks `_auto` on a hunch. Confirm that pick
against the price table this script prints (its `price_usd` column) before
trusting the mapping, and repoint the entry below if a different tier is the
one we actually mean to sell.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.fulfillment.suppliers.nova_client import (
    NovaClient,
    NovaError,
    NovaUnavailableError,
)
from yupay.modules.integrations.models import SkuSupplierMapping

SUPPLIER_SLUG = "nova"
#: `updated_by` audit value written on every mapping row this script touches.
UPDATED_BY = "seed:2026-09-17_nova_mappings"

BRAND_CATEGORIES: dict[str, str] = {
    # our brand slug -> their TOP-UP category id (not the validate namespace)
    #
    # What to expect from each, measured against their live catalogue on
    # 2026-09-17 — so that an operator reading a long unmatched table knows
    # whether the script is working or the catalogues simply differ:
    #
    # - `mobile_legends_ru` is our RU ladder exactly: all nine denominations
    #   match, and only the two passes are left by hand.
    # - `mobile_legends_global` is a DIFFERENT ladder. They sell 14/42/70/140/
    #   284/355/429/716/1446…, we sell 86/172/257/275/344/429/514… — `429
    #   Diamonds` is the only number in both. Expect one match and twenty-six
    #   lines to read. Their global catalogue does carry our pass SKUs by name
    #   (Weekly Elite Pack, Twilight Pass, Monthly Elite Pack), which is a
    #   by-hand mapping worth making.
    # - `pubg_mobile_auto` sells UC *and* WOW Coins under one category, with
    #   the same numbers on both ladders. That pair is exactly why the matcher
    #   below keys on the unit as well as the number.
    "mobile-legends-ru": "mobile_legends_ru",
    "mobile-legends": "mobile_legends_global",
    "pubg-mobile": "pubg_mobile_auto",
}

#: A denomination label: a number, then the unit it counts.
_DENOM = re.compile(r"^\s*(\d+)\s*(.*)$")

#: A digit-grouping separator, and only that: a comma or a space with a digit on
#: each side. Matched this narrowly on purpose — a blanket space strip would
#: join a number to whatever followed it.
_GROUPING = re.compile(r"(?<=\d)[\s,\u00a0](?=\d)")

#: What a denomination sells: how many, and of what. Both halves are the key.
_Denomination = tuple[int, frozenset[str]]


def _denomination(text: str | None) -> _Denomination | None:
    """A label's number and its unit words, or ``None`` if it is not a denomination.

    ``"275 Diamonds"`` -> ``(275, {"diamonds"})``;
    ``"1800 WOW Coins"`` -> ``(1800, {"wow", "coins"})``;
    ``"Weekly Elite Pack"`` -> ``None``.

    **The number must start the label, and the unit is part of the key.** Both
    halves of that rule were paid for by real rows in our own catalogue:

    - Without the anchor, ``"Elite Pass LV1-100"`` parses as ``1`` and
      ``"Prime (1 Month)"`` as ``1``, and either would map a subscription onto
      whatever offer happens to sell one of something. Every real denomination
      we sell reads ``"<n> <unit>"``; every pack reads as words.
    - Without the unit, ``"1800 UC"`` and ``"1800 WOW Coins"`` — both live
      under the ``pubg-mobile`` brand — are the same key, and NOVA's
      ``"1800 UC"`` would have been written onto both. A customer buying WOW
      Coins would have been sent UC.

    A unit spelled differently on the two sides (their ``"275 Diamond"``
    against our ``"275 Diamonds"``) simply does not match, and lands in the
    unmatched table for a human. That is the direction to be wrong in.
    """
    if not text:
        return None
    # "1,800 UC" and "1 800 UC" are the same denomination as "1800 UC". Without
    # this the number would stop at the separator and the remainder would leak
    # into the unit set, which fails safe (nothing matches) but puts a baffling
    # line in the unmatched table.
    m = _DENOM.match(_GROUPING.sub("", text))
    if m is None:
        return None
    units = frozenset(w for w in re.split(r"[^0-9a-z]+", m.group(2).lower()) if w)
    return (int(m.group(1)), units)


def _label(denom: _Denomination) -> str:
    """A denomination as an operator reads it: ``"1800 uc"``."""
    amount, units = denom
    return f"{amount} {' '.join(sorted(units))}".strip()


def _sku_denomination(sku: Any) -> _Denomination | None:  # Any: a Sku ORM row.
    """What this SKU sells, as a number and a unit.

    ``denomination`` is the only field consulted: it is the operator-facing
    label and the one that carries the unit. ``units`` holds a bare number with
    no unit beside it, so it cannot answer the half of the question that keeps
    UC out of a WOW Coins SKU, and ``sku_code`` is an identifier rather than a
    label.
    """
    return _denomination(sku.denomination)


@dataclass(frozen=True)
class _Matched:
    """One SKU that landed on exactly one NOVA offer."""

    sku_code: str
    offer_name: str
    cost_usdt: Decimal | None
    price_usd: str


@dataclass(frozen=True)
class _Unmatched:
    """One SKU a human has to finish mapping in the admin."""

    sku_code: str
    denomination: str | None
    reason: str


async def _load_skus(session: AsyncSession, *, brand_slug: str) -> list[Sku]:
    """Every SKU of every active product under ``brand_slug``."""
    return list(
        (
            await session.execute(
                select(Sku)
                .join(Product, Product.id == Sku.product_id)
                .join(Brand, Brand.id == Product.brand_id)
                .where(Brand.slug == brand_slug, Product.active.is_(True))
                .order_by(Sku.sku_code)
            )
        )
        .scalars()
        .all()
    )


def _offers_by_denomination(
    offers: list[dict[str, Any]],
) -> dict[_Denomination, list[dict[str, Any]]]:
    """Group offers by number *and* unit, dropping offers that are not denominations."""
    by_denom: dict[_Denomination, list[dict[str, Any]]] = {}
    for offer in offers:
        denom = _denomination(str(offer.get("name") or ""))
        if denom is not None:
            by_denom.setdefault(denom, []).append(offer)
    return by_denom


def _upsert_stmt(  # Any: an Insert whose generic parameters SQLAlchemy does not export.
    *, sku_id: str, category_id: str, offer_id: str
) -> Any:
    """The ``ON CONFLICT (sku_id, supplier_slug) DO UPDATE`` for one mapping."""
    return (
        pg_insert(SkuSupplierMapping)
        .values(
            sku_id=sku_id,
            supplier_slug=SUPPLIER_SLUG,
            kind="game",
            external_product_id=category_id,
            external_variant_id=offer_id,
            is_active=True,
            updated_by=UPDATED_BY,
        )
        .on_conflict_do_update(
            index_elements=[SkuSupplierMapping.sku_id, SkuSupplierMapping.supplier_slug],
            set_={
                "kind": "game",
                "external_product_id": category_id,
                "external_variant_id": offer_id,
                "is_active": True,
                "updated_by": UPDATED_BY,
            },
        )
    )


async def _match_brand(
    session: AsyncSession, client: NovaClient, *, brand_slug: str, category_id: str
) -> tuple[list[_Matched], list[_Unmatched]]:
    """Load one brand's SKUs, fetch NOVA's offers, pair them, upsert the matches.

    A denomination that matches more than one offer is reported as unmatched,
    never guessed — see the module docstring.
    """
    skus = await _load_skus(session, brand_slug=brand_slug)
    if not skus:
        print(f"{brand_slug} ({category_id}): no active SKUs — skipping")
        return [], []

    try:
        body = await client.get_offers(category_id)
    except (NovaError, NovaUnavailableError) as exc:
        raise SystemExit(f"cannot reach NOVA: {exc}") from exc

    offers = [o for o in (body.get("offers") or []) if isinstance(o, dict)]
    by_denom = _offers_by_denomination(offers)
    print(f"{brand_slug} ({category_id}): {len(skus)} sku(s), {len(offers)} nova offer(s)")

    # Two passes on purpose. The first decides; the second writes. Nothing is
    # upserted until every SKU of the brand has been resolved, because the last
    # guard below can only be applied once they all have: two of OUR SKUs can
    # land on one offer, and neither of them may be written when they do.
    claims: list[tuple[Any, dict[str, Any]]] = []
    matched: list[_Matched] = []
    unmatched: list[_Unmatched] = []
    for sku in skus:
        denom = _sku_denomination(sku)
        if denom is None:
            unmatched.append(
                _Unmatched(
                    sku.sku_code,
                    sku.denomination,
                    "not a denomination label (a pack or a subscription) — map it by hand",
                )
            )
            continue

        candidates = by_denom.get(denom, [])
        if not candidates:
            unmatched.append(
                _Unmatched(
                    sku.sku_code,
                    sku.denomination,
                    f"no NOVA offer for {_label(denom)} in {category_id} — map it by hand",
                )
            )
            continue
        if len(candidates) > 1:
            names = ", ".join(str(c.get("name")) for c in candidates)
            unmatched.append(
                _Unmatched(
                    sku.sku_code,
                    sku.denomination,
                    f"{_label(denom)} matches {len(candidates)} nova offers ({names})"
                    " — pick one by hand",
                )
            )
            continue

        offer = candidates[0]
        offer_id = str(offer.get("offer_id") or "").strip()
        offer_name = str(offer.get("name") or "")
        if not offer_id:
            unmatched.append(
                _Unmatched(
                    sku.sku_code,
                    sku.denomination,
                    f"matched offer {offer_name!r} has no offer_id — map it by hand",
                )
            )
            continue

        claims.append((sku, offer))

    # The mirror of the guard above, on our side of the pairing. NOVA's catalogue
    # is not the only one that can be ambiguous: a legacy row, a duplicate, or a
    # product whose label happens to read like a plain top-up can leave two of
    # our active SKUs claiming one offer. Writing both would send two different
    # products to the same thing, and the only trace would be two rows with the
    # same offer name in a table nobody reads twice. So neither is written.
    claimants: dict[str, list[str]] = {}
    for sku, offer in claims:
        claimants.setdefault(str(offer.get("offer_id") or "").strip(), []).append(sku.sku_code)

    for sku, offer in claims:
        offer_id = str(offer.get("offer_id") or "").strip()
        offer_name = str(offer.get("name") or "")
        rivals = claimants[offer_id]
        if len(rivals) > 1:
            others = ", ".join(c for c in rivals if c != sku.sku_code)
            unmatched.append(
                _Unmatched(
                    sku.sku_code,
                    sku.denomination,
                    f"{len(rivals)} of our SKUs claim {offer_name!r} ({others}) — map them by hand",
                )
            )
            continue
        await session.execute(
            _upsert_stmt(sku_id=sku.id, category_id=category_id, offer_id=offer_id)
        )
        matched.append(
            _Matched(sku.sku_code, offer_name, sku.cost_usdt, str(offer.get("price_usd") or ""))
        )

    return matched, unmatched


def _print_matched(rows: list[_Matched]) -> None:
    print(f"\nmatched ({len(rows)}):")
    if not rows:
        print("  (none)")
        return
    sku_w = max(len("sku_code"), *(len(r.sku_code) for r in rows))
    offer_w = max(len("nova offer"), *(len(r.offer_name) for r in rows))
    print(
        f"  {'sku_code'.ljust(sku_w)}  {'nova offer'.ljust(offer_w)}  {'cost_usdt':>10}  price_usd"
    )
    for r in rows:
        cost = str(r.cost_usdt) if r.cost_usdt is not None else "-"
        print(
            f"  {r.sku_code.ljust(sku_w)}  {r.offer_name.ljust(offer_w)}  {cost:>10}  {r.price_usd}"
        )


def _print_unmatched(rows: list[_Unmatched]) -> None:
    print(f"\nunmatched ({len(rows)}) — finish these in the admin:")
    if not rows:
        print("  (none)")
        return
    sku_w = max(len("sku_code"), *(len(r.sku_code) for r in rows))
    denom_w = max(len("denomination"), *(len(r.denomination or "-") for r in rows))
    print(f"  {'sku_code'.ljust(sku_w)}  {'denomination'.ljust(denom_w)}  why")
    for r in rows:
        denom = r.denomination or "-"
        print(f"  {r.sku_code.ljust(sku_w)}  {denom.ljust(denom_w)}  {r.reason}")


async def main() -> None:
    settings = get_settings()
    if not settings.nova_api_key:
        raise SystemExit("no NOVA API key configured — set NOVA_API_KEY and retry")

    client = NovaClient(
        api_key=settings.nova_api_key,
        base_url=settings.nova_base_url,
        timeout_seconds=settings.nova_request_timeout_seconds,
    )

    all_matched: list[_Matched] = []
    all_unmatched: list[_Unmatched] = []

    async with get_session_factory()() as session:
        for brand_slug, category_id in BRAND_CATEGORIES.items():
            matched, unmatched = await _match_brand(
                session, client, brand_slug=brand_slug, category_id=category_id
            )
            all_matched += matched
            all_unmatched += unmatched

        _print_matched(all_matched)
        _print_unmatched(all_unmatched)

        await session.commit()

    print(
        f"\n{len(all_matched)} mapping(s) written, {len(all_unmatched)} sku(s) left for the admin"
    )


if __name__ == "__main__":
    asyncio.run(main())
