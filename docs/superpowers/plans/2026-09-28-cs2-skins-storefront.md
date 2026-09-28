# CS2 Skins — Web Storefront Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only `/skins` section on yupay.uz — catalogue with filters, category bar, search, item page with wear tiles, float bar and live listings — priced and filtered in our **sell** price, in soʻm.

**Architecture:** Two API changes first: the sell price and the discount become stored columns (so filters and sorts use what the customer sees), and the item detail carries its wear family. Then the web pages: Server Components rendering from URL `searchParams` (filters are links and a GET form — no client state, crawlable, cheap on the bundle), with three small client islands (search-as-you-type, sort select, live listings). Buying is plan 3; the button says «Скоро».

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 / Alembic; Next.js 15 App Router, next-intl v4, Tailwind v4, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-28-cs2-skins-design.md` (§4.5 reads, §9 plan 2). Reference UX the owner pointed at: https://skinsavdo.uz/market (filters left, category bar with weapon menus, `×N` lot badge, item page with wear tiles, float bar, Seed/Paint, «Осмотр», Steam price link).

## Global Constraints

- **The customer filters and sorts by the price they see.** Every price filter and price/discount sort reads `skin_items.sell_price_usd` / `discount_percent`, written by the same `pricing.quote()` that renders the card. Supplier cost never reaches a filter.
- **Prices shown in soʻm** (`formatUzs`), filter inputs in soʻm; the API converts with the request's FX rate.
- **No Waxpeer call per grid card.** Only the item page's listings island calls `/skins/{slug}/listings` (the §10 carve-out, 18/min budget).
- **Server Components by default**; `"use client"` only for `SkinSearch`, `SkinSort`, `SkinListings`. Filter state lives in the URL.
- **Every user-facing string in `web.json` under `skins`, all three locales, same commit.** Item names stay English (spec §2.5).
- Web route JS budget ≤ 180 KB gzipped (unenforced; measure by hand with `next build` output for `/[locale]/skins`).
- The whole section 404s while `CS2_SKINS_ENABLED` is off (the API already does; pages call `notFound()` on a 404 catalogue).
- `ruff`, `mypy --strict`, `eslint`, `tsc`, `prettier --check .`. No pushing, no deploying. Branch: `feat/cs2-skins`.

## Review Focus

1. **Admin changes the pricing rules** → every card, filter bound and discount sort reflects the new sell price on the next page load (rows repriced in the same transaction as the rules write). Pinned in Task 1 (`test_rules_put_reprices_every_row`).
2. **A filter in soʻm with FX unavailable** → the page renders without price filters applied rather than 500. Pinned in Task 1 (`test_uzs_filter_without_fx_is_ignored`).
3. **A sold-out item's page** (`active = false`) → renders with «Нет в наличии» and its other wears, not 404. Pinned in Task 4 (`SkinPage` sold-out test).
4. **Listings island when the API answers `degraded: true`** → shows the snapshot prices with a «цены обновляются» note and no float/stickers. Pinned in Task 4.
5. **Arbitrary `searchParams`** (`?sort=evil&min=abc&cursor=%%%`) → parsed to safe defaults, never passed raw to the API. Pinned in Task 2 (`parseSkinQuery` tests).

---

## File Structure

| File                                                                        | Responsibility                                                                                                          |
| --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `apps/api/migrations/versions/0088_skins_sell_price.py`                     | `sell_price_usd`, `discount_percent` columns + indexes                                                                  |
| `apps/api/src/yupay/modules/skins/repricing.py`                             | `reprice_rows(db, rules, ids=None)` — writes sell price + discount for active rows                                      |
| `apps/api/src/yupay/modules/skins/{prices,admin,service,routes,schemas}.py` | use the stored columns; UZS filters; rarity filter/facet; `family` on detail                                            |
| `apps/web/src/lib/skins.ts`                                                 | types, server fetchers, `parseSkinQuery` / `skinQueryString`                                                            |
| `apps/web/src/lib/skin-float.ts`                                            | float → bar position and wear band                                                                                      |
| `apps/web/src/app/[locale]/skins/page.tsx`                                  | catalogue                                                                                                               |
| `apps/web/src/app/[locale]/skins/[slug]/page.tsx`                           | item                                                                                                                    |
| `apps/web/src/components/skins/*`                                           | `SkinCard`, `SkinFilters`, `SkinCategoryBar`, `SkinSearch`, `SkinSort`, `SkinWearTiles`, `SkinFloatBar`, `SkinListings` |
| `apps/web/src/components/{PrimaryNav,MobileNav}.tsx`, `app/sitemap.ts`      | entry points                                                                                                            |
| `packages/i18n/locales/{ru,en,uz}/web.json`                                 | `skins` namespace                                                                                                       |

---

## Task 1: API — stored sell price and discount, UZS filters, rarity, wear family

**Files:**

- Create: `apps/api/migrations/versions/0088_skins_sell_price.py`, `apps/api/src/yupay/modules/skins/repricing.py`
- Modify: `apps/api/src/yupay/modules/skins/models.py`, `prices.py` (`sync_prices`), `admin.py` (PUT rules, PATCH item), `service.py` (filters, sorts, cursor, facets), `routes.py` (UZS params, rarity, family), `schemas.py`
- Test: `apps/api/tests/integration/test_skins_sell_price.py`; update expectations in `test_skins_catalog_routes.py`, `test_skins_review_fixes.py`

**Interfaces:**

- Produces:
  - `SkinItem.sell_price_usd: Decimal | None` (Numeric(12,2)), `SkinItem.discount_percent: int | None`.
  - `repricing.reprice_rows(db, rules: PricingRules, *, ids: Sequence[str] | None = None) -> int` — recomputes both columns for active rows (all, or `ids`), sets them NULL on inactive ones; returns rows written.
  - `CatalogQuery` gains `rarity: str | None`, `min_usd`/`max_usd: Decimal | None` (replacing `min_units`/`max_units`).
  - `GET /skins/catalog` params: `min_uzs`, `max_uzs` (Decimal ≥ 0), `rarity`, plus the existing ones (`min_usd`/`max_usd` removed).
  - `SkinFacetsOut.rarities: list[FacetOut]`.
  - `SkinDetailOut.family: list[SkinFamilyMemberOut]` — `{slug, exterior, stattrak, souvenir, price_usd, price_uzs, count}` for every row with the same `category, weapon, skin, phase`, ordered FN→BS, StatTrak after plain.

- [ ] **Step 1: Failing tests** — `apps/api/tests/integration/test_skins_sell_price.py`:

```python
"""Filters and sorts use the stored sell price the card shows (plan 2, Task 1)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.fulfillment.suppliers.waxpeer_client import SnapshotRow
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.quote_settings import ManualOverride
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.naming import slug_for
from yupay.modules.skins.prices import aggregate, apply_prices
from yupay.modules.skins.pricing import DEFAULT_RULES
from yupay.modules.skins.repricing import reprice_rows

pytestmark = pytest.mark.asyncio
_RATE = Decimal("12700")


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CS2_SKINS_ENABLED", "true")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


async def _fx() -> None:
    await build_default_service().publish_quote_setting(
        ManualOverride(quote="UZS", use_manual=True, manual_rate=_RATE, updated_at=None)
    )


def _item(name: str, weapon: str, skin: str, ext: str, cost: int, **kw: object) -> SkinItem:
    return SkinItem(
        id=new_id(), market_hash_name=name, phase="", slug=slug_for(name, ""),
        category="rifles", weapon=weapon, skin=skin, exterior=ext, search_text=name.lower(),
        min_auto_units=cost, count_auto=10, active=True,
        cheapest_auto=[{"listing_id": 1, "price_units": cost}], **kw,
    )


async def test_price_tick_writes_sell_price_and_discount(db_session: AsyncSession) -> None:
    snap = [SnapshotRow(1, "AK-47 | Redline (Field-Tested)", 27867, True)]
    meta = [{"name": "AK-47 | Redline (Field-Tested)", "steam_price": 43794, "type": "Rifles"}]
    await apply_prices(db_session, aggregate(snap), meta=meta, at=now())
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    row = (await db_session.execute(select(SkinItem))).scalar_one()
    # 1 auto listing -> liquidity +3 pp: 1.80069 + 6 % × 27.867 = 3.47271 -> 31.34
    assert row.sell_price_usd == Decimal("31.34")
    assert row.discount_percent == 28  # (43.794 - 31.34) / 43.794 = 28.4 % -> 28


async def test_uzs_filter_uses_the_sell_price(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _fx()
    db_session.add_all(
        [
            _item("A | One (Field-Tested)", "A", "One", "FT", 9500),   # sells ~ $10.55
            _item("A | Two (Field-Tested)", "A", "Two", "FT", 8000),   # sells ~ $8.93
        ]
    )
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    r = await integration_client.get("/api/v1/skins/catalog", params={"max_uzs": str(10 * _RATE)})
    assert [i["name"] for i in r.json()["items"]] == ["A | Two (Field-Tested)"]


async def test_uzs_filter_without_fx_is_ignored(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yupay.modules.skins import routes

    async def no_rate(_fx: object) -> None:  # what ``_uzs_rate`` returns on an FX outage
        return None

    monkeypatch.setattr(routes, "_uzs_rate", no_rate)
    db_session.add(_item("A | One (Field-Tested)", "A", "One", "FT", 9500))
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    r = await integration_client.get("/api/v1/skins/catalog", params={"max_uzs": "1"})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1


async def test_detail_carries_the_wear_family(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _fx()
    db_session.add_all(
        [
            _item("AK-47 | Redline (Field-Tested)", "AK-47", "Redline", "FT", 27867),
            _item("AK-47 | Redline (Minimal Wear)", "AK-47", "Redline", "MW", 60000),
            _item("StatTrak™ AK-47 | Redline (Field-Tested)", "AK-47", "Redline", "FT", 80000, stattrak=True),
            _item("AK-47 | Asiimov (Field-Tested)", "AK-47", "Asiimov", "FT", 50000),
        ]
    )
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    body = (await integration_client.get("/api/v1/skins/ak-47-redline-field-tested")).json()
    fam = [(m["exterior"], m["stattrak"]) for m in body["family"]]
    assert fam == [("MW", False), ("FT", False), ("FT", True)]


async def test_rules_put_reprices_every_row(db_session: AsyncSession) -> None:
    db_session.add(_item("A | One (Field-Tested)", "A", "One", "FT", 9500))
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    before = (await db_session.execute(select(SkinItem.sell_price_usd))).scalar_one()
    richer = DEFAULT_RULES.model_copy(update={"expenses_percent": Decimal("20")})
    assert await reprice_rows(db_session, richer) == 1
    await db_session.commit()
    after = (await db_session.execute(select(SkinItem.sell_price_usd))).scalar_one()
    assert after is not None and before is not None and after > before
```

- [ ] **Step 2: Run, watch them fail** — `cd apps/api && uv run pytest tests/integration/test_skins_sell_price.py -q` → FAIL, `ModuleNotFoundError: yupay.modules.skins.repricing`.

- [ ] **Step 3: Migration + model columns**

```python
# apps/api/migrations/versions/0088_skins_sell_price.py
"""Skins: stored sell price and discount, so filters and sorts use what the card shows.

Revision ID: 0088_skins_sell_price
Revises: 0087_cs2_skins
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0088_skins_sell_price"
down_revision: str | None = "0087_cs2_skins"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("skin_items", sa.Column("sell_price_usd", sa.Numeric(12, 2), nullable=True))
    op.add_column("skin_items", sa.Column("discount_percent", sa.Integer(), nullable=True))
    op.create_index("ix_skin_items_category_sell", "skin_items", ["category", "sell_price_usd"])
    op.create_index("ix_skin_items_discount", "skin_items", ["discount_percent"])


def downgrade() -> None:
    op.drop_index("ix_skin_items_discount", table_name="skin_items")
    op.drop_index("ix_skin_items_category_sell", table_name="skin_items")
    op.drop_column("skin_items", "discount_percent")
    op.drop_column("skin_items", "sell_price_usd")
```

In `models.py`, after `fixed_price_usd`:

```python
    # ---- derived, written by ``repricing.reprice_rows`` (never by hand) ----
    #: Our sell price for the cheapest auto listing — what the card shows and
    #: what every price filter and sort reads. NULL while inactive.
    sell_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    #: Whole percent below Steam, truncated toward zero; NULL without a Steam price.
    discount_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 4: `repricing.py`**

```python
"""Write each row's sell price and discount from the pricing rules.

Runs after every price tick (inside ``sync_prices``' transaction) and after
every rules write or per-item override (inside the admin transaction), so
the stored numbers never disagree with what ``quote()`` would say.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.pricing import PricingRules, quote

_BATCH = 1000


def discount_of(price: Decimal, steam_price_units: int | None) -> int | None:
    """Whole percent below Steam, truncated toward zero (negative when dearer)."""
    if not steam_price_units:
        return None
    steam = Decimal(steam_price_units) / Decimal(1000)
    return int((steam - price) / steam * 100)


async def reprice_rows(
    db: AsyncSession, rules: PricingRules, *, ids: Sequence[str] | None = None
) -> int:
    """Recompute ``sell_price_usd``/``discount_percent``; returns rows written."""
    stmt = select(SkinItem)
    if ids is not None:
        stmt = stmt.where(SkinItem.id.in_(ids))
    rows = (await db.execute(stmt)).scalars().all()
    updates: list[dict[str, object]] = []
    for row in rows:
        if not row.active or row.min_auto_units is None:
            price, discount = None, None
        else:
            price = quote(
                row.min_auto_units,
                rules=rules,
                category=row.category,
                weapon=row.weapon,
                count_auto=row.count_auto,
                item_pp=row.margin_override_pp,
                fixed_price_usd=row.fixed_price_usd,
                steam_price_units=row.steam_price_units,
            ).price_usd
            discount = discount_of(price, row.steam_price_units)
        if (price, discount) != (row.sell_price_usd, row.discount_percent):
            updates.append({"id": row.id, "sell_price_usd": price, "discount_percent": discount})
    for start in range(0, len(updates), _BATCH):
        await db.execute(update(SkinItem), updates[start : start + _BATCH])
    return len(updates)


__all__ = ["discount_of", "reprice_rows"]
```

`int()` on a Decimal truncates toward zero, the same as Postgres integer division — keep it that way; the keyset cursor depends on it.

- [ ] **Step 5: Wire it in**

- `prices.sync_prices`: after `apply_prices(...)` and before `commit`, `await reprice_rows(db, await load_rules(db))` (import `load_rules` from `skins.settings`, `reprice_rows` from `skins.repricing`).
- `admin.admin_put_pricing`: after `save_rules(...)`, `await reprice_rows(db, body)`; commit; publish; bump version (order unchanged otherwise).
- `admin.admin_set_item_pricing`: after setting the fields, `await reprice_rows(db, await load_rules(db), ids=[item.id])`, then commit.

- [ ] **Step 6: Service — filters and sorts on the stored columns**

In `service.py`:

- `CatalogQuery`: replace `min_units`/`max_units` with `min_usd: Decimal | None = None`, `max_usd: Decimal | None = None`; add `rarity: str | None = None`.
- `_filtered`: `SkinItem.sell_price_usd >= query.min_usd` / `<= query.max_usd`; `SkinItem.rarity == query.rarity`.
- Delete `_DISCOUNT` and `_discount_of`. `_sort_column`: `discount` → `func.coalesce(SkinItem.discount_percent, -1000)`; `popular` → `SkinItem.count_auto`; price sorts → `SkinItem.sell_price_usd`.
- Cursor: the sort value is now a Decimal for price sorts. Encode it as a string in the JSON (`str(value)`), decode back to `Decimal` for price sorts and `int` otherwise. Update `encode_cursor(value: int | Decimal | None, item_id)` / `decode_cursor` accordingly and extend `test_skins_cursor.py` with a Decimal round-trip case. The last value comes straight from the row (`last.sell_price_usd`, `last.discount_percent or -1000`, `last.count_auto`) — no recomputation.
- `facets`: add `rarities=await count_by(SkinItem.rarity)`.
- New `family(db, item, *, categories) -> list[SkinItem]`: rows with the same `category, weapon, skin, phase` (skin may be NULL for vanilla knives — compare with `is_not_distinct_from`), ordered by exterior FN, MW, FT, WW, BS, NULL (a `case(...)`) then `stattrak`, then `souvenir`.

- [ ] **Step 7: Routes and schemas**

- `get_catalog`: drop `min_usd`/`max_usd`; add `min_uzs`, `max_uzs` (`Decimal`, `ge=0`, `le=10**12`), `rarity`. Convert with `rate = await _uzs_rate(_fx())`: `min_usd = min_uzs / rate` when both present; **when `rate is None` drop both bounds** (Review Focus 2). Include the converted bounds, not the soʻm ones, in the cache key.
- `_item_out`: read `price = item.sell_price_usd`, `discount = item.discount_percent` (positive only for display: `discount if discount and discount > 0 else None`). Keep `quote` for the per-listing prices in detail and listings.
- `SkinFacetsOut.rarities`, `SkinFamilyMemberOut`, `SkinDetailOut.family` in `schemas.py`; `get_detail` fills `family` from `service.family`.

- [ ] **Step 8: Update existing expectations**

`test_skins_catalog_routes.py` and `test_skins_review_fixes.py` seed rows directly: call `await reprice_rows(db_session, DEFAULT_RULES)` + commit after seeding. The discount-sort regression test keeps its intent (a zero Steam price does not 500; negatives page completely) — its rows now carry `discount_percent` via repricing. The AK card's `discount_percent` stays 31 (display clamps nothing positive).

- [ ] **Step 9: Run** — `cd apps/api && uv run pytest tests -k skins -q` → all pass. Then `uv run ruff check apps && uv run ruff format --check apps && uv run mypy apps`.

- [ ] **Step 10: Regenerate and commit**

```bash
make gen-api && npx prettier --write docs/api/openapi.json
git add apps/api docs/api/openapi.json
git commit -m "feat(api/skins): filter and sort by the stored sell price; rarity; wear family"
```

---

## Task 2: Web data layer — `lib/skins.ts`, `lib/skin-float.ts`

**Files:**

- Create: `apps/web/src/lib/skins.ts`, `apps/web/src/lib/skins.test.ts`, `apps/web/src/lib/skin-float.ts`, `apps/web/src/lib/skin-float.test.ts`

**Interfaces:**

- Produces (TypeScript):
  - Types `SkinItem`, `SkinsPage`, `SkinFacets`, `SkinDetail`, `SkinFamilyMember`, `SkinListing`, `SkinListings` mirroring the API DTOs (money as `string | null`).
  - `type SkinSort = "price" | "-price" | "discount" | "popular"`; `interface SkinQuery { category?, weapon?, exterior?, rarity?, stattrak?, q?, minUzs?, maxUzs?, sort: SkinSort, cursor? }`.
  - `parseSkinQuery(params: Record<string, string | string[] | undefined>): SkinQuery` — whitelists every field.
  - `skinQueryString(q: SkinQuery, patch?: Partial<SkinQuery>): string` — `?`-prefixed, stable key order, drops defaults and empties; `cursor` is dropped whenever any other field changes.
  - `getSkinsPage(locale, q)`, `getSkinFacets(locale)`, `getSkinDetail(locale, slug)` — server (`apiGet`, `revalidate: 60`, tag `skins`), never throw (empty page / `null`).
  - `fetchSkinListings(slug)` — client (`apiFetch`, anonymous).
  - `floatPosition(value: number): number` (0–100 %), `wearBand(value: number): "FN" | "MW" | "FT" | "WW" | "BS"`.

- [ ] **Step 1: Failing tests** — `skins.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { parseSkinQuery, skinQueryString } from "./skins";

describe("parseSkinQuery", () => {
  it("keeps known values and whitelists the rest", () => {
    const q = parseSkinQuery({
      category: "rifles",
      weapon: "AK-47",
      exterior: "FT",
      sort: "evil",
      min: "abc",
      max: "150000",
      cursor: "%%%",
      stattrak: "1",
      q: "  redline  ",
    });
    expect(q).toEqual({
      category: "rifles",
      weapon: "AK-47",
      exterior: "FT",
      sort: "price",
      maxUzs: 150000,
      stattrak: true,
      q: "redline",
    });
  });

  it("drops an unknown category and exterior", () => {
    expect(parseSkinQuery({ category: "../admin", exterior: "XX" })).toEqual({ sort: "price" });
  });

  it("takes the first value of a repeated param", () => {
    expect(parseSkinQuery({ weapon: ["AWP", "AK-47"] }).weapon).toBe("AWP");
  });

  it("accepts a well-formed cursor", () => {
    expect(parseSkinQuery({ cursor: "WzEsImEiXQ" }).cursor).toBe("WzEsImEiXQ");
  });
});

describe("skinQueryString", () => {
  it("drops defaults, keeps a stable order", () => {
    expect(skinQueryString({ sort: "price", weapon: "AWP", category: "rifles" })).toBe(
      "?category=rifles&weapon=AWP",
    );
    expect(skinQueryString({ sort: "price" })).toBe("");
  });

  it("resets the cursor when a filter changes", () => {
    expect(skinQueryString({ sort: "price", cursor: "abc" }, { exterior: "MW" })).toBe(
      "?exterior=MW",
    );
    expect(skinQueryString({ sort: "price" }, { cursor: "abc" })).toBe("?cursor=abc");
  });
});
```

`skin-float.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { floatPosition, wearBand } from "./skin-float";

describe("wearBand", () => {
  it.each([
    [0.0, "FN"],
    [0.069, "FN"],
    [0.07, "MW"],
    [0.149, "MW"],
    [0.15, "FT"],
    [0.379, "FT"],
    [0.38, "WW"],
    [0.449, "WW"],
    [0.45, "BS"],
    [1, "BS"],
  ])("%s -> %s", (v, band) => {
    expect(wearBand(v)).toBe(band);
  });
});

describe("floatPosition", () => {
  it("clamps to 0..100", () => {
    expect(floatPosition(-1)).toBe(0);
    expect(floatPosition(0.5)).toBe(50);
    expect(floatPosition(2)).toBe(100);
  });
});
```

- [ ] **Step 2: Run, watch them fail** — `cd apps/web && pnpm vitest run src/lib/skins.test.ts src/lib/skin-float.test.ts` → FAIL (module not found).

- [ ] **Step 3: `skin-float.ts`**

```ts
/** Steam's wear bands by float value — the thresholds CS2 itself uses. */
export type WearBand = "FN" | "MW" | "FT" | "WW" | "BS";

const BANDS: readonly (readonly [number, WearBand])[] = [
  [0.07, "FN"],
  [0.15, "MW"],
  [0.38, "FT"],
  [0.45, "WW"],
];

export function wearBand(value: number): WearBand {
  for (const [upper, band] of BANDS) if (value < upper) return band;
  return "BS";
}

/** Marker position on a 0..1 float bar, as a percent. */
export function floatPosition(value: number): number {
  return Math.min(100, Math.max(0, value * 100));
}
```

- [ ] **Step 4: `skins.ts`**

```ts
import { apiGet, apiGetOrNull } from "@/lib/api";
import { apiFetch } from "@/lib/client";

export type SkinSort = "price" | "-price" | "discount" | "popular";
export type Exterior = "FN" | "MW" | "FT" | "WW" | "BS";

export const SKIN_CATEGORIES = [
  "rifles",
  "pistols",
  "smgs",
  "heavy",
  "knives",
  "gloves",
  "agents",
  "cases",
  "keys",
  "music-kits",
  "charms",
] as const;
export type SkinCategory = (typeof SKIN_CATEGORIES)[number];
const SORTS: readonly SkinSort[] = ["price", "-price", "discount", "popular"];
const EXTERIORS: readonly Exterior[] = ["FN", "MW", "FT", "WW", "BS"];

export interface SkinItem {
  slug: string;
  name: string;
  phase: string | null;
  category: string;
  weapon: string | null;
  skin: string | null;
  exterior: Exterior | null;
  stattrak: boolean;
  souvenir: boolean;
  rarity: string | null;
  rarity_color: string | null;
  image_url: string | null;
  price_usd: string | null;
  price_uzs: string | null;
  steam_price_usd: string | null;
  discount_percent: number | null;
  count: number;
  min_float: string | null;
  max_float: string | null;
}
export interface SkinsPage {
  items: SkinItem[];
  next_cursor: string | null;
}
export interface Facet {
  value: string;
  count: number;
}
export interface SkinFacets {
  categories: Facet[];
  weapons: Facet[];
  exteriors: Facet[];
  rarities: Facet[];
}
export interface SkinFamilyMember {
  slug: string;
  exterior: Exterior | null;
  stattrak: boolean;
  souvenir: boolean;
  price_usd: string | null;
  price_uzs: string | null;
  count: number;
}
export interface SkinDetail extends SkinItem {
  cheapest: { listing_id: number; price_usd: string; price_uzs: string | null }[];
  family: SkinFamilyMember[];
}
export interface SkinListing {
  listing_id: number;
  price_usd: string;
  price_uzs: string | null;
  float_value: number | null;
  paint_seed: number | null;
  stickers: { name: string; image: string | null; slot: number | null; wear: number | null }[];
  inspect_url: string | null;
}
export interface SkinListings {
  items: SkinListing[];
  degraded: boolean;
}

export interface SkinQuery {
  category?: SkinCategory;
  weapon?: string;
  exterior?: Exterior;
  rarity?: string;
  stattrak?: boolean;
  q?: string;
  minUzs?: number;
  maxUzs?: number;
  sort: SkinSort;
  cursor?: string;
}

type Params = Record<string, string | string[] | undefined>;
const first = (v: string | string[] | undefined): string | undefined =>
  (Array.isArray(v) ? v[0] : v)?.trim() || undefined;
const SAFE_TEXT = /^[\p{L}\p{N} .|'™★()&-]{1,80}$/u;
const CURSOR = /^[A-Za-z0-9_-]{1,200}$/;

function amount(v: string | undefined): number | undefined {
  if (v === undefined || !/^\d{1,12}$/.test(v)) return undefined;
  return Number(v);
}

export function parseSkinQuery(params: Params): SkinQuery {
  const q: SkinQuery = { sort: "price" };
  const category = first(params.category);
  if (category && (SKIN_CATEGORIES as readonly string[]).includes(category)) {
    q.category = category as SkinCategory; // narrowed by the includes() check above
  }
  const weapon = first(params.weapon);
  if (weapon && SAFE_TEXT.test(weapon)) q.weapon = weapon;
  const exterior = first(params.exterior);
  if (exterior && (EXTERIORS as readonly string[]).includes(exterior)) {
    q.exterior = exterior as Exterior; // narrowed by the includes() check above
  }
  const rarity = first(params.rarity);
  if (rarity && SAFE_TEXT.test(rarity)) q.rarity = rarity;
  if (first(params.stattrak) === "1") q.stattrak = true;
  const text = first(params.q);
  if (text && SAFE_TEXT.test(text)) q.q = text;
  const min = amount(first(params.min));
  if (min !== undefined) q.minUzs = min;
  const max = amount(first(params.max));
  if (max !== undefined) q.maxUzs = max;
  const sort = first(params.sort);
  if (sort && (SORTS as readonly string[]).includes(sort)) q.sort = sort as SkinSort; // narrowed above
  const cursor = first(params.cursor);
  if (cursor && CURSOR.test(cursor)) q.cursor = cursor;
  return q;
}

const ORDER: readonly (keyof SkinQuery)[] = [
  "category",
  "weapon",
  "exterior",
  "rarity",
  "stattrak",
  "q",
  "minUzs",
  "maxUzs",
  "sort",
  "cursor",
];
const KEY: Record<keyof SkinQuery, string> = {
  category: "category",
  weapon: "weapon",
  exterior: "exterior",
  rarity: "rarity",
  stattrak: "stattrak",
  q: "q",
  minUzs: "min",
  maxUzs: "max",
  sort: "sort",
  cursor: "cursor",
};

export function skinQueryString(q: SkinQuery, patch: Partial<SkinQuery> = {}): string {
  const changesFilter = Object.keys(patch).some((k) => k !== "cursor");
  const merged: SkinQuery = { ...q, ...patch };
  if (changesFilter && !("cursor" in patch)) delete merged.cursor;
  const out = new URLSearchParams();
  for (const key of ORDER) {
    const v = merged[key];
    if (v === undefined || v === "" || v === false) continue;
    if (key === "sort" && v === "price") continue;
    out.set(KEY[key], v === true ? "1" : String(v));
  }
  const s = out.toString();
  return s ? `?${s}` : "";
}

function apiParams(q: SkinQuery): string {
  const p = new URLSearchParams();
  if (q.category) p.set("category", q.category);
  if (q.weapon) p.set("weapon", q.weapon);
  if (q.exterior) p.set("exterior", q.exterior);
  if (q.rarity) p.set("rarity", q.rarity);
  if (q.stattrak) p.set("stattrak", "true");
  if (q.q) p.set("q", q.q);
  if (q.minUzs !== undefined) p.set("min_uzs", String(q.minUzs));
  if (q.maxUzs !== undefined) p.set("max_uzs", String(q.maxUzs));
  p.set("sort", q.sort);
  if (q.cursor) p.set("cursor", q.cursor);
  p.set("limit", "48");
  return p.toString();
}

const OPTS = { revalidate: 60, tags: ["skins"] };

export async function getSkinsPage(locale: string, q: SkinQuery): Promise<SkinsPage> {
  try {
    return await apiGet<SkinsPage>(`/skins/catalog?${apiParams(q)}`, { locale, ...OPTS });
  } catch {
    return { items: [], next_cursor: null };
  }
}

export async function getSkinFacets(locale: string): Promise<SkinFacets | null> {
  try {
    return await apiGetOrNull<SkinFacets>("/skins/facets", { locale, ...OPTS });
  } catch {
    return null;
  }
}

export async function getSkinDetail(locale: string, slug: string): Promise<SkinDetail | null> {
  try {
    return await apiGetOrNull<SkinDetail>(`/skins/${encodeURIComponent(slug)}`, {
      locale,
      ...OPTS,
    });
  } catch {
    return null;
  }
}

export async function fetchSkinListings(slug: string): Promise<SkinListings> {
  return apiFetch<SkinListings>(`/skins/${encodeURIComponent(slug)}/listings`, { anonymous: true });
}
```

Check `apiFetch`'s option name for unauthenticated calls in `lib/client.ts` (`searchGifts` uses it) and match it exactly.

- [ ] **Step 5: Run, watch them pass** — same command → PASS.

- [ ] **Step 6: Commit**

```bash
cd apps/web && pnpm exec tsc --noEmit && pnpm exec eslint src/lib/skins.ts src/lib/skin-float.ts
git add apps/web/src/lib/skins.ts apps/web/src/lib/skins.test.ts apps/web/src/lib/skin-float.ts apps/web/src/lib/skin-float.test.ts
git commit -m "feat(web/skins): query parsing, fetchers and float helpers"
```

---

## Task 3: Catalogue page `/skins`

**Files:**

- Create: `apps/web/src/app/[locale]/skins/page.tsx`, `apps/web/src/app/[locale]/skins/loading.tsx`
- Create: `apps/web/src/components/skins/SkinCard.tsx`, `SkinCard.test.tsx`, `SkinFilters.tsx`, `SkinCategoryBar.tsx`, `SkinSearch.tsx`, `SkinSort.tsx`
- Modify: `packages/i18n/locales/{ru,en,uz}/web.json` (new `skins` namespace — keys listed in Step 3)

**Interfaces:**

- Consumes: everything from Task 2.
- Produces: `SkinCard({ item, locale })`, `SkinFilters({ query, facets, locale })`, `SkinCategoryBar({ query, facets, locale })`, `SkinSearch({ initial, locale })` (client), `SkinSort({ query, locale })` (client).

Layout (the skinsavdo reference, our design tokens): left column filters (price от/до in soʻm, wear checkboxes as links, rarity links); top bar with search, sort and category links; grid of cards 2 → 3 → 4 → 5 columns; «Показать ещё» as a link carrying `next_cursor`. Mobile: filters collapse into a `<details>` above the grid (no JS).

- [ ] **Step 1: Failing test** — `SkinCard.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "../../../../../packages/i18n/locales/ru/web.json";

import { SkinCard } from "./SkinCard";

import type { SkinItem } from "@/lib/skins";

const item: SkinItem = {
  slug: "ak-47-redline-field-tested",
  name: "AK-47 | Redline (Field-Tested)",
  phase: null,
  category: "rifles",
  weapon: "AK-47",
  skin: "Redline",
  exterior: "FT",
  stattrak: false,
  souvenir: false,
  rarity: "Classified",
  rarity_color: "#d32ce6",
  image_url: "https://community.akamai.steamstatic.com/economy/image/x",
  price_usd: "30.37",
  price_uzs: "385700",
  steam_price_usd: "43.794",
  discount_percent: 31,
  count: 49,
  min_float: "0.1",
  max_float: "0.7",
};

function renderCard(over: Partial<SkinItem> = {}) {
  return render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinCard item={{ ...item, ...over }} locale="ru" />
    </NextIntlClientProvider>,
  );
}

describe("SkinCard", () => {
  it("shows skin, weapon, wear, price in som, lot count and discount", () => {
    renderCard();
    expect(screen.getByText("Redline")).toBeInTheDocument();
    expect(screen.getByText(/AK-47/)).toBeInTheDocument();
    expect(screen.getByText("FT")).toBeInTheDocument();
    expect(screen.getByText(/385\s?700/)).toBeInTheDocument();
    expect(screen.getByText("×49")).toBeInTheDocument();
    expect(screen.getByText("−31%")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/skins/ak-47-redline-field-tested");
  });

  it("marks StatTrak and hides a missing discount", () => {
    renderCard({ stattrak: true, discount_percent: null });
    expect(screen.getByText("StatTrak™")).toBeInTheDocument();
    expect(screen.queryByText(/%$/)).not.toBeInTheDocument();
  });

  it("says sold out without a price", () => {
    renderCard({ price_uzs: null, price_usd: null, count: 0 });
    expect(screen.getByText("Нет в наличии")).toBeInTheDocument();
  });
});
```

Match the message-provider setup to an existing web component test (`components/store/ReviewAvatar.test.tsx` or `PurchasePanel.test.tsx`) if it differs.

- [ ] **Step 2: Run, watch it fail** — `pnpm vitest run src/components/skins/SkinCard.test.tsx` → FAIL.

- [ ] **Step 3: i18n** — add to `web.json` in all three locales (ru shown; en/uz translated in the same commit):

```json
"skins": {
  "meta": {
    "title": "Скины CS2 за сумы — купить в Узбекистане",
    "description": "Скины CS2 с моментальной доставкой: оружие, ножи, перчатки, агенты и кейсы. Оплата в сумах, цены обновляются каждые 5 минут.",
    "itemTitle": "{name} — купить за сумы",
    "itemDescription": "{name}: от {price}. Моментальная доставка обменом в Steam, оплата в сумах."
  },
  "title": "Маркет скинов CS2",
  "searchPlaceholder": "Название скина…",
  "filters": "Фильтры",
  "price": "Цена, сум",
  "from": "От",
  "to": "До",
  "apply": "Применить",
  "reset": "Сбросить",
  "wear": "Качество",
  "rarity": "Редкость",
  "stattrak": "Только StatTrak™",
  "sort": { "price": "Сначала дешевле", "-price": "Сначала дороже", "discount": "Выгоднее Steam", "popular": "Популярные" },
  "all": "Все",
  "category": {
    "rifles": "Винтовки", "pistols": "Пистолеты", "smgs": "ПП", "heavy": "Тяжёлое",
    "knives": "Ножи", "gloves": "Перчатки", "agents": "Агенты", "cases": "Кейсы",
    "keys": "Ключи", "music-kits": "Музыка", "charms": "Брелоки"
  },
  "exterior": { "FN": "Прямо с завода", "MW": "Немного поношенное", "FT": "После полевых", "WW": "Поношенное", "BS": "Закалённое в боях" },
  "soldOut": "Нет в наличии",
  "loadMore": "Показать ещё",
  "empty": "Ничего не нашлось. Попробуйте другое название или сбросьте фильтры.",
  "from_price": "от {price}",
  "steamPrice": "Steam",
  "offers": "Предложения",
  "inspect": "Осмотр в игре",
  "seed": "Seed",
  "float": "Float",
  "buySoon": "Покупка скоро",
  "updating": "Цены обновляются — показаны последние известные",
  "ready": "Мгновенно",
  "stickers": "Наклейки",
  "nav": "Скины CS2"
}
```

- [ ] **Step 4: `SkinCard.tsx`** — no `"use client"` (renders in the server grid); `next/image` with `unoptimized={!isOptimizable(src)}` and `sizes="(min-width:1280px) 20vw, (min-width:768px) 33vw, 50vw"`; a rarity-coloured bottom border (`style={{ borderBottomColor: item.rarity_color ?? undefined }}`); text: `item.skin ?? item.name` large, `{stattrak && "StatTrak™ "}{item.weapon}` small, exterior badge, `×{count}` badge top-left when `count > 1`, discount badge `−{n}%` when `n > 0`, price `formatUzs(locale, Math.round(Number(item.price_uzs)))` or `t("soldOut")`; whole card a `Link` to `pathFor(locale, "/skins/" + slug)`.

- [ ] **Step 5: Filters, category bar, search, sort**

- `SkinCategoryBar` (server): «Все» + one link per category present in `facets.categories`, each `skinQueryString(query, { category, weapon: undefined })`; when a category is active, a second row of weapon links from `facets.weapons` (the API facets are global; filter to weapons seen in the current page's items when the category is set — good enough for v1, noted in the component).
- `SkinFilters` (server): a `<form method="get">` with hidden inputs carrying the current `category`, `weapon`, `q`, `sort`; two number inputs `min`/`max`; submit «Применить», link «Сбросить» to `pathFor(locale, "/skins")`. Wear and rarity as link lists (active one highlighted, clicking the active one removes it). StatTrak as a link toggle.
- `SkinSearch` (`"use client"`): input with 250 ms debounce calling `apiFetch('/skins/suggest?q=…', { anonymous: true })`, dropdown of up to 10 results linking to their pages; Enter submits `?q=` via `router.push(pathFor(locale, "/skins") + skinQueryString(...))`. Abort the previous request on each keystroke (`AbortController`).
- `SkinSort` (`"use client"`): a `<select>` whose `onChange` does `router.push` with `skinQueryString(query, { sort })`.

- [ ] **Step 6: `page.tsx`**

```tsx
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import Link from "next/link";

import type { Metadata } from "next";

import { SkinCard } from "@/components/skins/SkinCard";
import { SkinCategoryBar } from "@/components/skins/SkinCategoryBar";
import { SkinFilters } from "@/components/skins/SkinFilters";
import { SkinSearch } from "@/components/skins/SkinSearch";
import { SkinSort } from "@/components/skins/SkinSort";
import { routing } from "@/i18n/routing";
import { getSkinFacets, getSkinsPage, parseSkinQuery, skinQueryString } from "@/lib/skins";
import { alternates, GEO_META, localeUrl, ogLocale, pathFor, ROBOTS } from "@/lib/seo";

const PATH = "/skins";

type Props = {
  params: Promise<{ locale: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export async function generateMetadata({ params, searchParams }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const filtered = Object.keys(await searchParams).length > 0;
  return {
    title: t("meta.title"),
    description: t("meta.description"),
    alternates: alternates(locale, PATH),
    other: GEO_META,
    // A filtered view is a duplicate of the hub for a crawler.
    robots: filtered ? { index: false, follow: true } : ROBOTS,
    openGraph: {
      type: "website",
      siteName: "YuPay",
      title: t("meta.title"),
      url: localeUrl(locale, PATH),
      ...ogLocale(locale),
    },
  };
}

export default async function SkinsPage({ params, searchParams }: Props) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  const t = await getTranslations("web.skins");
  const query = parseSkinQuery(await searchParams);
  const [page, facets] = await Promise.all([getSkinsPage(locale, query), getSkinFacets(locale)]);
  if (facets === null) notFound(); // the section is off (API 404) or unreachable

  return (
    <main className="mx-auto max-w-7xl px-4 py-6 lg:flex lg:gap-6">
      <aside className="lg:w-64 lg:shrink-0">
        <SkinFilters query={query} facets={facets} locale={locale} />
      </aside>
      <section className="min-w-0 flex-1">
        <h1 className="font-display mb-4 text-2xl font-bold">{t("title")}</h1>
        <div className="mb-3 flex flex-col gap-3 sm:flex-row">
          <SkinSearch initial={query.q ?? ""} locale={locale} query={query} />
          <SkinSort query={query} locale={locale} />
        </div>
        <SkinCategoryBar query={query} facets={facets} locale={locale} items={page.items} />
        {page.items.length === 0 ? (
          <p className="text-tx-mute py-16 text-center">{t("empty")}</p>
        ) : (
          <ul className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {page.items.map((item) => (
              <li key={item.slug}>
                <SkinCard item={item} locale={locale} />
              </li>
            ))}
          </ul>
        )}
        {page.next_cursor && (
          <Link
            href={pathFor(locale, PATH) + skinQueryString(query, { cursor: page.next_cursor })}
            className="border-border mx-auto mt-6 block w-fit rounded-xl border px-6 py-3 font-semibold"
          >
            {t("loadMore")}
          </Link>
        )}
      </section>
    </main>
  );
}
```

`loading.tsx`: a grid of 10 skeleton cards using the same classes. Match the design tokens and wrapper components (`main` container, headings) used by `store/steam-gifts/page.tsx` rather than the raw classes above if they differ.

- [ ] **Step 7: Run tests and a local render**

```bash
cd apps/web && pnpm vitest run src/components/skins src/lib/skins.test.ts && pnpm exec tsc --noEmit && pnpm exec eslint src/app/\[locale\]/skins src/components/skins
```

With the API running locally and `CS2_SKINS_ENABLED=true` + seeded rows (Task 1 fixtures or a real sync), open `http://localhost:3000/skins` and `?category=rifles&exterior=FT&sort=-price&max=500000`; check the filters round-trip through the URL.

- [ ] **Step 8: Commit** — `git commit -m "feat(web/skins): catalogue page with URL filters, search and sort"`

---

## Task 4: Item page `/skins/[slug]`

**Files:**

- Create: `apps/web/src/app/[locale]/skins/[slug]/page.tsx`
- Create: `apps/web/src/components/skins/SkinWearTiles.tsx`, `SkinFloatBar.tsx`, `SkinListings.tsx`, `SkinListings.test.tsx`, `SkinWearTiles.test.tsx`

**Interfaces:**

- Consumes: `getSkinDetail`, `fetchSkinListings`, `floatPosition`, `wearBand`, `SkinDetail`, `SkinListings`.
- Produces: `SkinWearTiles({ family, current, locale })` (server), `SkinFloatBar({ value, min, max })` (server), `SkinListings({ slug, locale })` (client).

Page (skinsavdo layout): breadcrumb (Маркет / weapon); left the image; right the weapon (small) and `skin, wear` (large), `SkinFloatBar` for the cheapest listing once loaded (client-side, inside `SkinListings`' header), the price in soʻm, a Steam link (`https://steamcommunity.com/market/listings/730/{encodeURIComponent(name)}`, `rel="nofollow noopener"`), a disabled primary button «Покупка скоро»; below, `SkinWearTiles` (one tile per family member: wear code, full wear name, «от {price}», count; current one highlighted; StatTrak members as a second row), then `SkinListings`.

- [ ] **Step 1: Failing tests**

`SkinWearTiles.test.tsx`: renders three family members, asserts the current one has `aria-current="page"`, each links to its slug, sold-out member shows «Нет в наличии» instead of a price.

`SkinListings.test.tsx`: mock `fetchSkinListings` (`vi.mock("@/lib/skins", ...)` keeping the real exports except the fetcher):

```tsx
it("renders live listings with float, seed and inspect", async () => {
  mocked.mockResolvedValue({
    degraded: false,
    items: [
      {
        listing_id: 1,
        price_usd: "30.37",
        price_uzs: "385700",
        float_value: 0.3692,
        paint_seed: 421,
        stickers: [{ name: "Sticker | X", image: null, slot: 1, wear: null }],
        inspect_url: "steam://rungame/730/1/+csgo_econ_action_preview%20S1A1D1",
      },
    ],
  });
  renderListings();
  expect(await screen.findByText("0.3692")).toBeInTheDocument();
  expect(screen.getByText("421")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Осмотр/ })).toHaveAttribute(
    "href",
    expect.stringMatching(/^steam:\/\//),
  );
  expect(screen.queryByText(/обновляются/)).not.toBeInTheDocument();
});

it("says prices are updating and hides float when degraded", async () => {
  mocked.mockResolvedValue({
    degraded: true,
    items: [
      {
        listing_id: 1,
        price_usd: "30.37",
        price_uzs: "385700",
        float_value: null,
        paint_seed: null,
        stickers: [],
        inspect_url: null,
      },
    ],
  });
  renderListings();
  expect(await screen.findByText(/обновляются/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Осмотр/ })).not.toBeInTheDocument();
});

it("shows the empty state on a fetch error", async () => {
  mocked.mockRejectedValue(new Error("down"));
  renderListings();
  expect(await screen.findByText(/Нет в наличии/)).toBeInTheDocument();
});
```

A page-level test for Review Focus 3 (sold out): render `SkinWearTiles` + the page's price block with a detail whose `price_uzs` is `null` — assert «Нет в наличии» and that the family tiles still render. (Server-component page rendering is not unit-tested in this repo; keep the sold-out logic in a small `SkinPriceBlock` server component and test that.)

- [ ] **Step 2: Run, watch them fail.**

- [ ] **Step 3: Implement** the three components and the page. `SkinListings`: `useEffect` → `fetchSkinListings(slug)`; states `loading | ready | error`; each row: price (soʻm), float (4 decimals) with a mini `SkinFloatBar`, seed, sticker names (images only when the URL host ends with `steamstatic.com` or `akamaihd.net` — the deferred review minor, closed here on the client), «Мгновенно» badge (every listing we show is `auto`), «Осмотр в игре» link when `inspect_url` starts with `steam://`, and a disabled «Купить» per row. The page: `generateMetadata` from `t("meta.itemTitle", { name })` / `t("meta.itemDescription", { name, price })`, `alternates(locale, "/skins/" + slug)`, `robots: ROBOTS`; `notFound()` when `getSkinDetail` returns `null`; `revalidate` via the fetcher (60 s).

- [ ] **Step 4: Run tests, tsc, eslint; open a real item locally** (`/skins/ak-47-redline-field-tested`), check listings load, degrade (stop the API's Waxpeer key) and wear tiles switch.

- [ ] **Step 5: Commit** — `git commit -m "feat(web/skins): item page with wear tiles, float bar and live listings"`

---

## Task 5: Entry points, SEO, bundle, docs

**Files:**

- Modify: `apps/web/src/components/PrimaryNav.tsx`, `MobileNav.tsx`, `Footer.tsx`, the component that passes nav labels (search `PrimaryNav` usages), `apps/web/src/app/sitemap.ts`
- Modify: `docs/superpowers/specs/2026-09-28-cs2-skins-design.md` (§9: plan 2 split into web + miniapp), `apps/api/src/yupay/modules/skins/README.md`, `docs/architecture/module-map.md` (web section row if the file lists web routes)
- Create: `docs/product/flows/skins-browse.md` (Mermaid: catalogue → item → listings, degraded path)

- [ ] **Step 1: Nav** — add a «Скины CS2» link (`t("skins.nav")`, `pathFor(locale, "/skins")`, `navSectionActive`) after «Магазин» in `PrimaryNav` and `MobileNav`, and in the footer's catalogue column. The link renders only when a server-side flag says the section is on: probing the API per request would be too expensive, so add `NEXT_PUBLIC_SKINS_ENABLED` to the web env (`apps/web/.env.example`, `infra` compose files) and gate the link on it. Document the variable in the runbook's "Opening the storefront" section (web needs it too).
- [ ] **Step 2: Sitemap** — add only `/skins` (priority 0.8, `changeFrequency: "hourly"`). Filtered URLs are `noindex` by design, and item pages are deferred (24k URLs; spec §9, like Steam Gifts' per-game pages).
- [ ] **Step 3: Bundle** — `cd apps/web && pnpm build` and record the gzipped first-load JS for `/[locale]/skins` and `/[locale]/skins/[slug]` in the PR notes against the 180 KB budget; if over, move whatever pushed it (likely `SkinSearch`) behind `next/dynamic` with `ssr: false`.
- [ ] **Step 4: Docs** — the flow file, spec §9 note, README "Storefront" section listing the pages and the env flag.
- [ ] **Step 5: Full checks and commit**

```bash
make lint typecheck && pnpm --filter @yupay/web test && cd apps/api && uv run pytest tests -k skins -q
npx prettier --check .
git commit -m "feat(web/skins): nav, sitemap, flow doc; env flag for the section"
```

---

## Out of scope (next plans)

- **Miniapp** `/cs2-market`: the same reads in the Vite SPA (`wouter`, `useT`, `miniapp.json`) — plan 2b, reusing `lib/skins.ts`' query logic by moving `parseSkinQuery`/`skinQueryString` to `packages/utils` when it starts.
- **Purchase** (plan 3): trade link capture and storage (none exists today — `steam_links` holds only `steam_id`/persona), pre-checks, the ready gate, fulfilment, `skin_trades`, order page states.
- **SEO pages per item** — deferred like Steam Gifts'.
