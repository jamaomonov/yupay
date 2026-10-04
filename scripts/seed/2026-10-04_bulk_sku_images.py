"""Give the bulk-imported SKUs artwork from a sibling brand of the same game.

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-10-04_bulk_sku_images.py
    docker exec -i -e APPLY=1 yupay-prod-api-1 python - < scripts/seed/2026-10-04_bulk_sku_images.py

Free Fire (CIS) has a picture per diamond rung; Free Fire (BR) sells the same
diamonds and has none. Same for Mobile Legends' regional and Exclusive/Special
variants, Magic Chess Go Go's, Delta Force Garena's. The picture is of the
in-game currency, not the region, so it carries over.

For every SKU with no artwork of its own (and no product artwork to fall back
on), a donor is looked for among brands with the same title once the region
and variant are stripped («Free Fire (BR)» → «free fire»):

1. the donor SKU with the same denomination key (quantity + unit, or the
   normalised name — the import's own matcher);
2. else, for a quantity rung, the donor rung in the same unit nearest in size
   («1166 Diamonds» gets the «1080 Diamonds» picture — the same icon at a
   different count);
3. else the donor product's own picture, if it has one.

Passes and bundles with no name match get nothing: a diamonds picture on a
Weekly Pass would be wrong. The URL is copied, not the object — one file on
the CDN, many rows. Idempotent: a SKU that has artwork is left alone.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections import defaultdict
from typing import Any

import yupay.main  # noqa: F401 -- registers every model
from sqlalchemy import text
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Product, Sku

APPLY = os.environ.get("APPLY") == "1"

# The import's denomination matcher, copied verbatim from
# ``2026-10-04_bulk_topup_import.py`` (this file runs from stdin inside the
# container, where that one is not on disk).
FIRST = re.compile(r"first|1st|double|первое", re.I)
SPECIAL = re.compile(
    r"pass|weekly|monthly|membership|card|subscription|bundle|pack|prime|plus|elite|starlight|"
    r"welkin|battle|season|lite|vip|gift|express|privilege|package|offer|chest|bag|box|month|"
    r"week|day",
    re.I,
)
UNIT_ALIAS = {"unknown cash": "uc", "bc": "gold", "dm": "diamonds"}
NOISE = {"bonus", "x", "web", "top", "up", "global", "the"}


def denom_key(name: str) -> tuple[Any, ...]:
    low = name.replace(",", "").replace("\u00a0", " ").replace("'", "").lower()
    bare = re.sub(r"\(.*?\)", " ", low)
    first = bool(FIRST.search(low))
    plus = re.findall(r"(\d+)\s*(?:[a-z ]{0,20})?\+\s*(\d+)", bare)
    nums = re.findall(r"(?<![\w.])(\d{1,7})(?![\w.]*\d)", bare)
    total = int(plus[0][0]) + int(plus[0][1]) if plus else (int(nums[0]) if nums else None)
    words = [w for w in re.sub(r"[^a-z ]+", " ", bare).split() if w not in NOISE and w != "id"]
    unit = " ".join(words[:2])
    for alias, canon in UNIT_ALIAS.items():
        if unit == alias or unit.startswith(alias + " "):
            unit = canon
    unit = re.sub(r"s\b", "", unit)
    if total is None or (SPECIAL.search(low) and not re.match(r"^\s*\d", low)):
        # The whole name, brackets included: «Prime (1 Month)» and «Prime (3
        # Months)» are two products, and a key that dropped the brackets kept one.
        tagged = [w for w in re.sub(r"[^a-z0-9 ]+", " ", low).split() if w not in NOISE]
        return ("NAME", re.sub(r"s\b", "", " ".join(tagged)), first)
    return ("QTY", total, unit, first)


ALIASES = {
    "garena free fire": "free fire",
    "garena deltaforce": "delta force",
    "garena delta force": "delta force",
    "mobile legends bang bang": "mobile legends",
    "magic chess go go": "magic chess gogo",
    "codm garena": "call of duty mobile garena",
}


def title(name: str) -> str:
    t = re.sub(r"\(.*?\)", " ", name).lower().replace("-", " ")
    t = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()
    return ALIASES.get(t, t)


async def rows() -> list[dict[str, Any]]:
    async with get_session_factory()() as db:
        res = await db.execute(text("""
            select b.slug brand, t.name brand_name, p.id product_id, p.image_url product_image,
                   s.id sku_id, s.denomination, s.image_url
              from brands b join brand_translations t on t.brand_id = b.id and t.locale = 'ru'
              join products p on p.brand_id = b.id join skus s on s.product_id = p.id
             where p.kind = 'top_up'
        """))  # fmt: skip
        return [dict(r) for r in res.mappings().all()]


def plan(all_rows: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str], dict[str, int]]:  # noqa: PLR0912 -- three fallbacks, read top to bottom
    """(sku_id → image_url, product_id → image_url, per-brand counts)."""
    by_title: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in all_rows:
        by_title[title(r["brand_name"])].append(r)
    sku_out: dict[str, str] = {}
    product_out: dict[str, str] = {}
    counts: dict[str, int] = defaultdict(int)
    for group in by_title.values():
        donors = [r for r in group if r["image_url"]]
        if not donors:
            continue
        exact: dict[tuple[Any, ...], str] = {}
        by_unit: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for d in donors:
            k = denom_key(d["denomination"] or "")
            exact.setdefault(k, d["image_url"])
            if k[0] == "QTY":
                by_unit[k[2]].append((k[1], d["image_url"]))
        donor_product_image = next((r["product_image"] for r in donors if r["product_image"]), None)
        for r in group:
            if r["image_url"] or r["product_image"]:
                continue
            k = denom_key(r["denomination"] or "")
            url = exact.get(k)
            if url is None and k[0] == "QTY" and by_unit.get(k[2]):
                url = min(by_unit[k[2]], key=lambda q: abs(q[0] - k[1]))[1]
            if url is None and donor_product_image:
                url = donor_product_image
            if url:
                sku_out[r["sku_id"]] = url
                counts[r["brand"]] += 1
        if donor_product_image:
            for r in group:
                if not r["product_image"]:
                    product_out.setdefault(r["product_id"], donor_product_image)
    return sku_out, product_out, counts


async def main() -> None:
    sku_out, product_out, counts = plan(await rows())
    for brand, n in sorted(counts.items()):
        print(f"  {brand:40s} {n:4d} SKU")
    print(f"Картинок для SKU: {len(sku_out)}, для продуктов: {len(product_out)}")
    if not APPLY:
        print("APPLY не задан — ничего не записано.")
        return
    async with get_session_factory()() as db, db.begin():
        for sku_id, url in sku_out.items():
            sku = await db.get(Sku, sku_id)
            if sku is not None and sku.image_url is None:
                sku.image_url = url
        for product_id, url in product_out.items():
            product = await db.get(Product, product_id)
            if product is not None and product.image_url is None:
                product.image_url = url
    print("Записано.")


if __name__ == "__main__":
    asyncio.run(main())
