# Steam Gifts — Country Region Selector (v2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Branch: `main` (feature is live behind `STEAM_GIFTS_ENABLED=true` on prod — every change ships to real buyers).

**Goal:** Replace the opaque zone chips (CIS / RU / KZ / UA) with a concrete country picker («Узбекистан», «Таджикистан», …) plus a "how to find your Steam region" hint, without changing what we send to the supplier.

**Architecture:** G-Engine prices a package per **zone** (41 entries; each carries one representative country code + flag). A zone is the pricing unit and stays the wire unit; a **country** becomes the UI unit. A curated in-code map expands each offered zone into the countries it covers (Steam's CIS region = AM/AZ/BY/GE/KG/MD/TJ/TM/UZ). The buyer picks a country, we price from its zone and send that zone's own `region_code` — the value already proven to work end to end.

**Tech Stack:** FastAPI + Pydantic v2 (backend), Next.js 15 App Router (web), Vite + React 19 + wouter (miniapp), `Intl.DisplayNames` for localized country names, emoji flags from regional-indicator code points (no network, no asset host).

**Spec:** `docs/superpowers/specs/2026-09-02-steam-gifts-design.md` (§4.2/§4.3 pricing + region contract) as amended by the supplier's 2026-09-03 correction (wire `region` = the 2-letter code present in the package's own `prices[]`) and the operator's 2026-09-03 UX direction (show concrete countries; add a "how to find your region" hint).

## Global Constraints

- **The wire value never changes.** `fulfillment_data.region_code` — the value the fulfiller sends to G-Engine — stays the `region` field of the chosen zone's price entry (CIS → `ge`). A country code that is not one of the package's own 41 region codes must NEVER reach the supplier: it returns «Price not found».
- **Verified upstream shape** (live, 2026-09-03): each `packages[].prices[]` entry = `{zone, region, currency, price, flag_url}`; 41 entries; `zone` values include CIS/RU/KZ/UA; `region` is lowercase 2-letter (CIS → `ge`, EURO → `fr`, LATAM → `ar`, MENA → `tr`, SASIA → `pk`).
- **`fulfillment_data` keys are frozen**: the seeded product's `required_fields` are exactly `app_id`, `package_id`, `region`, `invite_url`; `validate_fulfillment_data` 422s any unknown key. So the country travels in the EXISTING `region` key — its _value_ changes from a zone label to a country code. Do not add a new key and do not touch the seed's `required_fields`.
- **Backwards compatibility**: `price_gift_line` must still accept a legacy zone label (`CIS`, `RU`, `KZ`, `UA`) in `region` — any order created before this ships, or a client that hasn't reloaded, must keep working.
- Money: `Decimal` server-side, strings on the wire, `Number()` only for display formatting.
- Country names come from `Intl.DisplayNames(locale, {type: "region"})`; flags are emoji built from the code — **no hardcoded country-name lists in i18n files and no external flag-image host**.
- Only the four zones in `STEAM_GIFTS_REGIONS` (default `CIS,RU,KZ,UA`) are sellable; the country expansion never widens what we sell.
- TS strict, no `any`, no uncommented `as`; mypy --strict; ruff; Google docstrings.
- Every new user-facing string lands in ru + en + uz in the same task (web = nested `web.json`, miniapp = flat-key `miniapp.json`).
- Conventional Commits; do NOT push and do NOT deploy — the operator runs both.
- Never stage the pre-existing dirty files: `Makefile`, `scripts/seed.py`, `scripts/seed/2026-08-21_telegram_stars_unit_sku.py`.

---

### Task R1: Backend — country expansion, DTO, checkout resolution

**Files:**

- Modify: `apps/api/src/yupay/modules/gifts/service.py` (country map + resolver)
- Modify: `apps/api/src/yupay/modules/gifts/schemas.py` (`GiftRegionOut`, `GiftAppDetailOut.regions`)
- Modify: `apps/api/src/yupay/modules/gifts/routes.py` (`_package_out`, detail assembly)
- Modify: `apps/api/src/yupay/modules/gifts/checkout.py` (`price_gift_line` accepts a country)
- Modify: `apps/api/src/yupay/core/config.py` (`steam_gifts_region_default` → `"UZ"`)
- Modify: `docs/runbooks/steam-gifts.md` (Regions section)
- Test: `apps/api/tests/unit/test_gifts_service.py`, `apps/api/tests/unit/test_gifts_checkout.py`, `apps/api/tests/integration/test_gifts_catalog_routes.py`, `apps/api/tests/integration/test_checkout_steam_gift.py`

**Interfaces produced** (R2/R3 consume verbatim):

```python
#: Steam prices these countries as one region; G-Engine bills the zone.
ZONE_COUNTRIES: dict[str, tuple[str, ...]] = {
    "CIS": ("UZ", "KZ" ...),  # NOTE: KZ has its OWN zone — see the real map below
}
```

The real map — offered zones only, uppercase ISO-3166-1 alpha-2:

- `"RU": ("RU",)`
- `"KZ": ("KZ",)`
- `"UA": ("UA",)`
- `"CIS": ("UZ", "GE", "KG", "MD", "TJ", "TM", "AM", "AZ", "BY")` — UZ first (our home market); the rest as listed.

A zone absent from the map falls back to `(entry["region"].upper(),)` — its own representative country — so adding a zone to `STEAM_GIFTS_REGIONS` never crashes.

New public functions in `service.py`:

- `def zone_for_country(country: str, *, offered: Sequence[str]) -> str | None` — reverse lookup over `ZONE_COUNTRIES` restricted to `offered`; case-insensitive; `None` when the country is not sold.
- `def countries_for_zone(zone: str, package: dict[str, Any]) -> tuple[str, ...]` — the map entry, or the package price entry's own `region` upper-cased as a single-element fallback.

**Steps:**

- [ ] **Step 1: unit tests first** (`test_gifts_service.py`) — `zone_for_country("uz", offered=["CIS","RU","KZ","UA"]) == "CIS"`; `zone_for_country("KZ", ...) == "KZ"` (its own zone wins over any CIS membership); `zone_for_country("DE", ...) is None`; `zone_for_country("UZ", offered=["RU"]) is None` (respects the offered list); `countries_for_zone("CIS", pkg)[0] == "UZ"`; unmapped zone falls back to the package entry's own region.
- [ ] **Step 2: run — FAIL.**
- [ ] **Step 3: implement the map + both resolvers in `service.py`.**
- [ ] **Step 4: run — PASS.**
- [ ] **Step 5: DTO + detail assembly.** Add to `schemas.py`:

```python
class GiftRegionOut(BaseModel):
    """One purchasable country, priced from the zone that covers it."""

    country: str      # "UZ" — what the buyer picks and what we accept back
    zone: str         # "CIS" — the pricing unit, for support/debugging
    price_usd: str
    price_uzs: str | None
```

`GiftAppDetailOut` gains `regions: list[GiftRegionOut]` and `region_default: str` (the country, default `"UZ"`). **Keep** the existing `zones`/`zone_default` fields for one release so a stale client keeps rendering — mark them deprecated in the docstring. In `routes.py`, build `regions` by iterating offered zones → `countries_for_zone` → one entry per country carrying that zone's sell price (so every CIS country shows the identical CIS price). Order: `region_default` first, then the remaining countries of its zone, then the other zones' countries in `STEAM_GIFTS_REGIONS` order. `GiftPackageOut.prices` (per-zone) stays as-is — R2/R3 price from `regions`, but the per-package zone prices remain the source for a package switch.

- [ ] **Step 6: checkout resolution.** In `price_gift_line`, the `region` value from `fulfillment_data` is now a **country code**: upper-case it, resolve `zone = zone_for_country(value, offered=offered_zones(settings))`; when that returns `None`, fall back to treating the value as a legacy zone label (`value in offered_zones(...)` → use it directly) so pre-v2 orders still price; otherwise raise the existing "this region has no price for the selected edition" `ValidationError`. Price from the resolved zone exactly as today, and enrich the snapshot with `data["region"] = <country or legacy zone, canonical upper>`, `data["zone"] = <resolved zone>`, `data["region_code"] = zone_region_code(package, zone)`. The fulfiller is untouched — it already prefers `region_code`.
- [ ] **Step 7: checkout + route tests.** `test_gifts_checkout.py`: `region="UZ"` prices from the CIS entry and snapshots `zone="CIS"`, `region_code="ge"`; `region="uz"` (lower) works; `region="CIS"` (legacy label) still works; `region="DE"` 422s. `test_gifts_catalog_routes.py`: detail exposes `regions` with UZ first, every CIS country carrying the same price, and no country outside the offered zones.
- [ ] **Step 8: run the four suites — PASS.** Then `uv run pytest apps/api/tests -k gifts -q` from repo root.
- [ ] **Step 9: config default + runbook.** `steam_gifts_region_default` default becomes `"UZ"` (prod has no env override — verified 2026-09-03 — so the code default is what ships). Update the runbook's Regions section: zones are the pricing/wire unit, countries are the UI unit, the curated map lives in `service.py::ZONE_COUNTRIES`, and widening `STEAM_GIFTS_REGIONS` only needs an api restart (the map falls back to a zone's own representative country).
- [ ] **Step 10: gates + commit.** ruff, `mypy apps` (repo-root invocation), prettier on the runbook, `make gen-api` (the detail DTO changed — CI's `openapi-drift` gate will fail without it; commit `docs/api/openapi.json`).

```bash
git add apps/api/src/yupay/modules/gifts apps/api/src/yupay/core/config.py apps/api/tests docs/runbooks/steam-gifts.md docs/api/openapi.json
git commit -m "feat(api/gifts): sell by country, price by zone"
```

---

### Task R2: Web — country picker + region hint

**Files:**

- Modify: `apps/web/src/lib/gifts.ts` (DTO types)
- Modify: `apps/web/src/components/gifts/GiftPurchasePanel.tsx` (selector + hint + warning)
- Create: `apps/web/src/lib/regions.ts` (+ `regions.test.ts`) — shared, framework-free helpers
- Modify: `packages/i18n/locales/{ru,en,uz}/web.json`
- Test: `apps/web/src/components/gifts/GiftPurchasePanel.test.tsx` (extend)

**Interfaces produced** (R3 mirrors this file, it does not import it — different app):

```ts
/** "UZ" -> "🇺🇿". Two regional-indicator code points, nothing fetched. */
export function flagEmoji(country: string): string;
/** "UZ" + "ru" -> "Узбекистан"; falls back to the raw code. */
export function countryName(country: string, locale: string): string;
```

`countryName` uses `Intl.DisplayNames([locale], {type: "region"})` inside a try/catch (a locale with no region data, or an unknown code, returns the code itself).

**Behaviour:**

- `GiftAppDetail` gains `regions: GiftRegion[]` (`{country, zone, price_usd, price_uzs}`) and `region_default: string`; the deprecated `zones`/`zone_default` stay in the type as optional so a build against the older deployed API still type-checks.
- The selector renders **countries**: flag emoji + localized name, priced from the selected package. Default = `region_default` (UZ). Keep the existing collapse rule — first four visible, the rest behind «другой регион» — because CIS alone is nine countries.
- A country whose zone has no price for the selected package renders disabled **with visible text** (not a `title=` tooltip — invisible on mobile), reusing the existing `noPriceInRegion` copy.
- New hint link «Как узнать регион?» next to the selector label, opening the same disclosure component the invite guide uses, with this copy (ru; translate for en/uz):
  > Чтобы узнать регион вашего Steam-аккаунта, нажмите на свой профиль в правом верхнем углу Steam, выберите «Об аккаунте» и посмотрите пункт «Страна» на открывшейся странице — store.steampowered.com/account.
- A short always-visible warning under the selector: «Регион должен совпадать со страной Steam-аккаунта получателя».
- The buy body is unchanged in shape — `fulfillment_data.region` now carries the **country code**.
- Selection reconciliation on package switch keeps the chosen country when its zone still has a price for the new package, else falls back to `region_default` (mirror the existing `zoneAfterPackageChange` rule, now keyed by country).

**Steps:** tests first (`regions.test.ts`: `flagEmoji("UZ") === "🇺🇿"`, unknown code returns the code, `countryName("UZ","ru")` is non-empty and ≠ `"UZ"`; panel test: default country is UZ, switching country re-prices, POST body carries `region: "UZ"`, a priceless country is disabled) → fail → implement → pass → `pnpm --filter @yupay/web test -- --run`, `tsc --noEmit`, lint, locale parity. Commit `feat(web): pick a Steam gift region by country, with a how-to-find-it hint`.

---

### Task R3: Miniapp — country picker + region hint

**Files:**

- Modify: `apps/miniapp/src/lib/gifts.ts` (DTO types + `priceFor`/`reconcileSelection` keyed by country)
- Create: `apps/miniapp/src/lib/regions.ts` (+ `regions.test.ts`) — same two helpers as R2, copied deliberately (separate app, no shared package for this)
- Modify: `apps/miniapp/src/components/gifts/ZonePill.tsx` → country pill (rename the file to `RegionPill.tsx` and update its importers), `apps/miniapp/src/pages/GiftGame.tsx`, `apps/miniapp/src/components/gifts/GiftBuyPanel.tsx` as needed
- Create: `apps/miniapp/src/components/gifts/RegionGuideSheet.tsx` — the «Как узнать регион?» sheet, mirroring `InviteGuideSheet.tsx`
- Modify: `packages/i18n/locales/{ru,en,uz}/miniapp.json` (flat dotted keys)
- Test: `apps/miniapp/src/pages/GiftGame.test.tsx` (extend), `apps/miniapp/src/lib/gifts.test.ts` (extend)

**Behaviour:** identical to R2, adapted to the miniapp's conventions — pills instead of a dropdown, a `Sheet` for the hint (same component the invite guide uses), `useT()` flat keys, and **node-env tests over exported pure logic only** (no RTL/jsdom in this app): export and test the country reconcile/selection helpers rather than rendering.

**Steps:** tests first → fail → implement → pass → `pnpm --filter @yupay/miniapp test -- --run`, typecheck, lint, locale parity. Visual smoke on the running dev miniapp (`:3001`) if it is serving. Commit `feat(miniapp): pick a Steam gift region by country, with a how-to-find-it hint`.
