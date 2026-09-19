"""What our suppliers sell that we do not — read-only, writes nothing.

Two gaps, and they are different kinds of opportunity:

1. **Missing denominations inside a brand we already sell.** This is the
   Free Fire shape: we listed nine G2B packs while NOVA carried nineteen,
   and the extra ten (Evo Access, Level Up, Newbie Bundle) were sellable
   the whole time. Same brand, same fulfilment path, nothing to build.

2. **Games no brand of ours covers at all.** Only those carried by more
   than one supplier are listed: a title two independent suppliers stock
   is one they can both actually deliver, and it keeps a 306-row dump from
   drowning the answer.

The denomination matcher is the one from
``scripts/seed/2026-09-19_backfill_nova_gengine_mappings.py`` — suppliers
spell a pack "base + bonus" where we spell the total, so the join key is
the sum. Keep the two in step; if that file's rule changes, this one is
wrong the same day.

    docker compose -f docker-compose.prod.yml exec -T api \\
        python - < scripts/check_catalog_gaps.py
"""

from __future__ import annotations

import asyncio
import re

from sqlalchemy import select
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.integrations.models import SkuSupplierMapping, SupplierCatalogCache

# brand slug -> supplier game id, copied from the backfill script. Region is
# chosen by hand there and the reason is in its docstring.
PAIRS: dict[str, dict[str, str]] = {
    "pubg-mobile": {"nova": "pubg_mobile_auto", "gengine": "8"},
    "mobile-legends": {"nova": "mobile_legends_global", "gengine": "44"},
    "mobile-legends-ru": {"nova": "mobile_legends_ru", "gengine": "5"},
    "delta-force": {"nova": "delta_force", "gengine": "9"},
    "free-fire": {"nova": "free_fire_cis"},
    "arena-breakout": {"nova": "arena_breakout", "gengine": "13"},
    "arena-breakout-infinite": {"nova": "arena_breakout_infinite"},
    "magic-chess-gogo": {"nova": "magic_chess_gogo_global", "gengine": "38"},
    "magic-chess-gogo-ru": {"nova": "magic_chess_gogo_ru", "gengine": "66"},
    "blood-strike": {"nova": "blood_strike", "gengine": "25"},
    "whiteout-survival": {"nova": "whiteout_survival"},
    "genshin-impact": {"nova": "genshin_impact_global", "gengine": "11"},
    "honkai-star-rail": {"nova": "honkai_star_rail_global", "gengine": "10"},
    "oxide-survival-island": {"nova": "oxide_survival_island"},
}


def norm(text: str) -> str:
    """Lowercase, collapse non-alphanumerics, and write "30 days" as "30d".

    That last step is not cosmetic: NOVA lists ``Bulletproof Case (30d)``
    where our SKU says ``Bulletproof Case (30 days)``, and Free Fire's own
    SKUs already say ``Evo Access 30d``. One spelling, chosen to match the
    shorter one both sides already use somewhere.
    """
    flat = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return re.sub(r"\b(\d+)\s+days?\b", r"\1d", flat)


#: Same unit, different word. Only pairs confirmed against live prices and an
#: identical denomination ladder go here.
#:
#: * ``unknown cash`` — G-Engine's "60 Unknown Cash" is $0.9180 against the
#:   $0.9000 we pay for "60 UC", and NOVA lists the same pack as "60 UC".
#: * ``bc`` — NOVA's Blood Strike ladder is 51/105/320/540/1100/2260/5800 "BC",
#:   the same seven values we and G-Engine call "Gold"/"Golds", at prices
#:   within a few percent. Checked before adding: "BC" appears in no other
#:   game's denominations, so this cannot leak into another catalogue.
#:
#: Deliberately *not* here: G-Engine's Genshin "Chronal Nexus", which runs the
#: same 60/330/1090/2240/3880/8080 ladder *alongside* its Genesis Crystals at
#: different prices. A second product at the same tiers is not a synonym, and
#: treating it as one would sell the wrong thing.
_UNIT_ALIASES = {"unknown cash": "uc", "bc": "gold"}

#: "1980 + 260 genesis crystals" — NOVA, and G-Engine on some games.
_AMOUNT_LEADING = re.compile(r"^(\d+)\s*\+\s*(\d+)\s+(.+)$")
#: "156 diamonds + 16 bonus" — G-Engine's other spelling, bonus last.
_AMOUNT_TRAILING = re.compile(r"^(\d+)\s+(.+?)\s*\+\s*(\d+)\s+bonus$")
#: "2240 genesis crystals" — ours, and G2B's.
_AMOUNT_PLAIN = re.compile(r"^(\d+)\s+(.+)$")


def amount_key(text: str) -> tuple[int, str] | None:
    """Total units and unit name, or ``None`` when the title is not a quantity.

    Suppliers quote a pack as base plus bonus where we and G2B quote the
    total, so the total is the join key. Verified on production: our six
    Genshin SKUs sell through G2B as 60/330/1090/2240/3880/8080 and NOVA's
    six titles sum to exactly those.

    Two spellings of the bonus exist and both are handled — NOVA's
    ``1980 + 260 Genesis Crystals`` and G-Engine's
    ``156 Diamonds + 16 Bonus``. Missing the second cost 30-odd G-Engine
    mappings on the first pass; they looked like honest gaps in the
    supplier's catalogue rather than a parser that could not read it.

    Whatever follows the digits stays in the key, which is what keeps
    NOVA's one-off ``150 + 15 Diamonds (First Top-Up Bonus)`` — also 165 —
    out of the plain ``165 Diamonds`` bucket.
    """
    # Not ``norm``: that strips "+" along with the rest of the punctuation.
    flat = re.sub(r"[^a-z0-9+]+", " ", text.lower()).strip()
    flat = re.sub(r"\b(\d+)\s+days?\b", r"\1d", flat)

    m = _AMOUNT_LEADING.match(flat)
    if m is not None:
        total, unit = int(m.group(1)) + int(m.group(2)), m.group(3)
    else:
        m = _AMOUNT_TRAILING.match(flat)
        if m is not None:
            total, unit = int(m.group(1)) + int(m.group(3)), m.group(2)
        else:
            m = _AMOUNT_PLAIN.match(flat)
            if m is None:
                return None
            total, unit = int(m.group(1)), m.group(2)
    # Suppliers disagree on plurals — "Oneiric Shard" against our "Oneiric
    # Shards", "Golds" against our "Gold". Strip a trailing "s" on both sides
    # so the two meet, but only at the very end and never after
    # "s", "i" or "u" — otherwise it eats the "s" of "bonus", or turns
    # "genesis crystals" into "genesi crystal".
    unit = re.sub(r"(?<![siu])s$", "", unit)
    return total, _UNIT_ALIASES.get(unit, unit)


def game_name(title: str) -> str:
    """Title without a trailing region qualifier, for cross-supplier compare."""
    return norm(re.sub(r"\s*[\(\[][^)\]]*[)\]]\s*$", "", title))


async def main() -> None:
    async with get_session_factory()() as db:
        # ---------- 1. denominations missing inside brands we sell ----------
        print("=" * 78)
        print("MISSING DENOMINATIONS — brands we already sell")
        print("=" * 78)

        total_gaps = 0
        for brand, per_supplier in PAIRS.items():
            skus = (
                (
                    await db.execute(
                        select(Sku)
                        .join(Product, Product.id == Sku.product_id)
                        .join(Brand, Brand.id == Product.brand_id)
                        .where(Brand.slug == brand)
                    )
                )
                .scalars()
                .all()
            )
            ours_titles = {norm(s.denomination) for s in skus if s.denomination}
            ours_amounts = {amount_key(s.denomination) for s in skus if s.denomination} - {None}

            # supplier denom -> the suppliers offering it, keyed so the same
            # pack from two suppliers is one line, not two.
            gaps: dict[tuple[str, str], list[tuple[str, object]]] = {}
            for supplier, game_id in per_supplier.items():
                # What an active mapping already points at. Matching titles is
                # how the *backfill* finds candidates, but it is the wrong
                # measure of coverage here: a pack reached through an explicit
                # alias — oxide's "50 + 5 WEB BONUS" for our "55 Coins
                # (50 + 5)" — is sold, however little its name looks like ours.
                # Counting those as gaps overstated this report by fifteen.
                already = {
                    row.external_variant_id
                    for row in (
                        await db.execute(
                            select(SkuSupplierMapping).where(
                                SkuSupplierMapping.supplier_slug == supplier,
                                SkuSupplierMapping.external_product_id == game_id,
                                SkuSupplierMapping.is_active.is_(True),
                            )
                        )
                    )
                    .scalars()
                    .all()
                    if row.external_variant_id
                }
                denoms = (
                    (
                        await db.execute(
                            select(SupplierCatalogCache).where(
                                SupplierCatalogCache.supplier_slug == supplier,
                                SupplierCatalogCache.kind == "game_denom",
                                SupplierCatalogCache.parent_external_id == game_id,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for d in denoms:
                    if d.external_id in already:
                        continue
                    key = amount_key(d.title)
                    if norm(d.title) in ours_titles or (key is not None and key in ours_amounts):
                        continue
                    label = (str(key[0]).rjust(9), key[1]) if key else ("", norm(d.title))
                    gaps.setdefault(label, []).append((supplier, d.price_usdt, d.title))

            if not gaps:
                continue
            print(f"\n{brand}  ({len(skus)} SKUs today, {len(gaps)} not sold)")
            for (amount, unit), sources in sorted(gaps.items()):
                where = ", ".join(
                    f"{s}" + (f" ${float(p):.4f}" if p is not None else "") for s, p, _t in sources
                )
                name = f"{amount.strip()} {unit}".strip()
                # Their own wording too, not just our computed total: the total
                # is what makes two suppliers one line, but the raw title is
                # what anyone writing an alias has to copy. Printing only the
                # total once sent me looking for a "55 WEB BONUS" that NOVA
                # spells "50 + 5 WEB BONUS".
                raw = {t for _s, _p, t in sources if norm(t) != f"{amount.strip()} {unit}".strip()}
                suffix = f"   [{' / '.join(sorted(raw))}]" if raw else ""
                print(f"    {name:<46} {where}{suffix}")
                total_gaps += 1

        print(f"\n  -> {total_gaps} denominations sold upstream that we do not list.\n")

        # ---------- 2. games no brand of ours covers ----------
        print("=" * 78)
        print("GAMES WE DO NOT SELL — carried by more than one supplier")
        print("=" * 78)

        ours = {game_name(b) for b in (await db.execute(select(Brand.slug))).scalars()}
        # Every game any active mapping already points at, read from the
        # database rather than from PAIRS above. PAIRS only covers the brands
        # this script pairs by hand, so using it here counted Telegram, Steam
        # and Standoff 2 — all of which we do sell, through mappings PAIRS
        # never mentions — as games we do not.
        mapped_ids = {
            (row.supplier_slug, row.external_product_id)
            for row in (
                await db.execute(
                    select(SkuSupplierMapping).where(SkuSupplierMapping.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        }

        games = (
            (
                await db.execute(
                    select(SupplierCatalogCache).where(SupplierCatalogCache.kind == "game")
                )
            )
            .scalars()
            .all()
        )
        by_name: dict[str, set[str]] = {}
        titles: dict[str, str] = {}
        for g in games:
            if (g.supplier_slug, g.external_id) in mapped_ids:
                continue
            name = game_name(g.title)
            if name in ours:
                continue
            by_name.setdefault(name, set()).add(g.supplier_slug)
            titles.setdefault(name, g.title)

        multi = {n: s for n, s in by_name.items() if len(s) > 1}
        for name, suppliers in sorted(multi.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            print(f"    {titles[name]:<46} {', '.join(sorted(suppliers))}")
        print(f"\n  -> {len(multi)} games carried by 2+ suppliers and absent from our catalogue.")
        print(f"     ({len(by_name) - len(multi)} more are carried by a single supplier.)")


if __name__ == "__main__":
    asyncio.run(main())
