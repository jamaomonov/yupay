"""Give bare-number SKU labels their unit, and name the Global Free Fire channel.

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-10-05_bare_labels.py
    docker exec -i -e APPLY=1 yupay-prod-api-1 python - < scripts/seed/2026-10-05_bare_labels.py

G2B names many top-up rungs by the number alone («341», «6160»); the bulk
import kept those labels when no other supplier named the same rung, so 261
SKUs read as a bare number on the reseller shelf. The unit is taken from the
labels around them: the brand's own «N Unit» rungs when they all agree on one
unit, else a same-title sibling brand's (Magic Chess GoGo (MY) from the other
Magic Chess GoGo brands). A brand with no unit anywhere stays as it is — a
guess would be worse than a number.

Also renames «Garena Free Fire» (G2B ``freefire_global`` + G-Engine) to
«Free Fire (Global)», matching the other regional Free Fire brands; our retail
``free-fire`` is the CIS channel. Idempotent.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections import Counter, defaultdict
from typing import Any

import yupay.main  # noqa: F401 -- registers every model
from sqlalchemy import text
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Sku

APPLY = os.environ.get("APPLY") == "1"
BARE = re.compile(r"^\s*[0-9][0-9,. ]*\s*$")
WITH_UNIT = re.compile(r"^\s*[0-9][0-9,. ]*\s+([A-Za-z][A-Za-z ]{1,20})$")
RENAME = {"garena-free-fire": "Free Fire (Global)"}
SIBLING_ALIASES = {
    "garena deltaforce": "delta force",
    "garena delta force": "delta force",
    "magic chess go go": "magic chess gogo",
    "mobile legends bang bang": "mobile legends",
}


def title_key(name: str) -> str:
    t = re.sub(r"\(.*?\)", " ", name).lower()
    t = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()
    return SIBLING_ALIASES.get(t, t)


async def rows() -> list[dict[str, Any]]:
    async with get_session_factory()() as db:
        res = await db.execute(text("""
            select b.id brand_id, b.slug, t.name brand_name, s.id sku_id, s.denomination
              from skus s join products p on p.id = s.product_id join brands b on b.id = p.brand_id
              join brand_translations t on t.brand_id = b.id and t.locale = 'ru'
             where s.active
        """))  # fmt: skip
        return [dict(r) for r in res.mappings().all()]


def plan(all_rows: list[dict[str, Any]]) -> dict[str, tuple[str, str, str]]:
    """sku_id -> (brand slug, old label, new label)."""
    brand_units: dict[str, Counter[str]] = defaultdict(Counter)
    title_units: dict[str, Counter[str]] = defaultdict(Counter)
    for r in all_rows:
        m = WITH_UNIT.match(r["denomination"] or "")
        if m:
            unit = m.group(1).strip()
            brand_units[r["brand_id"]][unit] += 1
            title_units[title_key(r["brand_name"])][unit] += 1

    def single(c: Counter[str]) -> str | None:
        kinds = {u.lower() for u in c}
        return c.most_common(1)[0][0] if len(kinds) == 1 else None

    out: dict[str, tuple[str, str, str]] = {}
    for r in all_rows:
        label = r["denomination"] or ""
        if not BARE.match(label):
            continue
        unit = single(brand_units[r["brand_id"]]) or single(title_units[title_key(r["brand_name"])])
        if unit:
            out[r["sku_id"]] = (r["slug"], label, f"{label.strip()} {unit}"[:64])
    return out


async def main() -> None:
    changes = plan(await rows())
    per_brand = Counter(slug for slug, _o, _n in changes.values())
    print(f"Голых номиналов с понятной единицей: {len(changes)}")
    for slug, n in sorted(per_brand.items()):
        sample = next(f"«{o}» → «{nw}»" for s, o, nw in changes.values() if s == slug)
        print(f"  {slug:36s} {n:3d}  {sample}")
    for slug, name in RENAME.items():
        print(f"Переименование: {slug} → «{name}»")
    if not APPLY:
        print("APPLY не задан — ничего не записано.")
        return
    async with get_session_factory()() as db, db.begin():
        for sku_id, (_s, old, new) in changes.items():
            sku = await db.get(Sku, sku_id)
            if sku is not None and sku.denomination == old:
                sku.denomination = new
        for slug, name in RENAME.items():
            res = await db.execute(text("select id from brands where slug = :s"), {"s": slug})
            brand_id = res.scalar_one_or_none()
            if brand_id is None:
                continue
            await db.execute(
                text("update brand_translations set name = :n where brand_id = :b"),
                {"n": name, "b": brand_id},
            )
    print("Записано.")


if __name__ == "__main__":
    asyncio.run(main())
