# CS2 Skins — Mini App Storefront (plan 2b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mini app's «Маркет скинов — скоро» screen with the read-only CS2 skins
catalogue and item page, served by the same `/skins/*` API as the web storefront.

**Architecture:** The query model (`SkinQuery`, parse/serialise, categories, sorts) and the
DTO types move from `apps/web/src/lib/skins.ts` to `packages/utils/src/skins.ts`, and the
float/image helpers from `apps/web/src/lib/skin-float.ts` to `packages/utils/src/skin-float.ts`;
web re-exports them, so its imports do not change. The mini app gets `src/lib/skins.ts`
(fetchers + price text), a catalogue page at `/cs2-market` whose filters live in the URL query
(wouter `useSearch`), and an item page at `/cs2-market/:slug`. Both are lazy chunks. The
feature gate is the API itself: every `/skins/*` read 404s while `cs2_skins_enabled` is off,
and the catalogue page shows the existing "скоро" screen on that 404 — no build flag.

**Tech Stack:** Vite 5 + React 19 SPA, wouter 3, `useT` flat-key catalogs
(`packages/i18n/locales/{ru,en,uz}/miniapp.json`), vitest (node env — pure logic only, no
jsdom), `@yupay/utils`.

**Spec:** `docs/superpowers/specs/2026-09-28-cs2-skins-design.md` (§9 item 2: 2b miniapp).
Web counterpart: `docs/superpowers/plans/2026-09-28-cs2-skins-storefront.md`.

## Global Constraints

- Read-only. The buy button renders disabled with «Покупка скоро»; purchase is plan 3.
- Filters and sorts use the stored sell price (API `min_uzs`/`max_uzs`, `sort`), as on web.
- Prices: soʻm when the API converted, dollars when FX is down, «Нет в наличии» only when
  there is no price at all — keyed on `price_usd` (the web I1 fix).
- No service meta in copy (owner rule 2026-09-28): no "prices update every N minutes", no note
  on degraded listings.
- Nothing Waxpeer-branded on the page. Seller info and the inspect link may be shown.
- Miniapp bundle: both pages are `lazy()` chunks; the entry chunk must not grow.
- All new strings in ru/en/uz `miniapp.json` in the same commit; `messages.test.ts` asserts parity.
- TS strict, `exactOptionalPropertyTypes`, no `any`; files ≤ 300 LOC.

## Review Focus

1. Feature off (API 404 on `/skins/facets`) → the "скоро" screen, not an error screen or an empty grid.
2. Telegram back from an item page → the catalogue with the same filters (state lives in the URL).
3. FX down → dollar prices, not «Нет в наличии» (Task 2 test).
4. An API 5xx on the item page → a retry state, not "not found" (Task 2 test: detail throws on non-404).
5. A hand-typed/garbled query string → safe defaults (shared `parseSkinQuery`, already tested; test moves with it).

---

### Task 1: Share the query model and helpers via `@yupay/utils`

**Files:**
- Create: `packages/utils/src/skins.ts`, `packages/utils/src/skins.test.ts` (moved from `apps/web/src/lib/skins.test.ts`)
- Create: `packages/utils/src/skin-float.ts`, `packages/utils/src/skin-float.test.ts` (moved from web)
- Modify: `packages/utils/src/index.ts` (export both)
- Modify: `apps/web/src/lib/skins.ts` (keep fetchers + `displayPrice`; re-export the rest from `@yupay/utils`)
- Modify: `apps/web/src/lib/skin-float.ts` (becomes `export * from "@yupay/utils"` subset)

**Interfaces:**
- Produces (from `@yupay/utils`): `SkinSort`, `Exterior`, `SKIN_CATEGORIES`, `SkinCategory`,
  `DEFAULT_SORT`, `EXTERIORS`, `SkinItem`, `SkinsPage`, `Facet`, `SkinFacets`,
  `SkinFamilyMember`, `SkinDetail`, `SkinListing`, `SkinListings`, `SkinQuery`,
  `SkinQueryPatch`, `parseSkinQuery(params: Record<string, string | string[] | undefined>)`,
  `skinQueryString(q, patch?)`, `wearBand`, `floatPosition`, `steamImageSize`.

- [ ] **Step 1:** `git mv` the two web test files into `packages/utils/src/`, change their import to `./skins` / `./skin-float`.
- [ ] **Step 2:** Run `cd packages/utils && pnpm vitest run` — Expected: FAIL, module `./skins` not found.
- [ ] **Step 3:** Move the pure code (types, constants, `parseSkinQuery`, `skinQueryString`, `first`, `amount`, regexes) verbatim into `packages/utils/src/skins.ts`; move `skin-float.ts` verbatim. Export `EXTERIORS` (the miniapp filter sheet lists it). Add both to `index.ts`. Web `lib/skins.ts` keeps `apiParams`, fetchers, `displayPrice`, and `export * from`/`export type *` the moved names so every web import still resolves.
- [ ] **Step 4:** Run utils tests, then `cd apps/web && pnpm exec tsc --noEmit && pnpm vitest run` — Expected: PASS, web 697/697 (the two moved files now count under utils).
- [ ] **Step 5:** Commit `refactor(utils): share the CS2 skins query model and float helpers`.

### Task 2: Mini app `lib/skins.ts` — fetchers and price text

**Files:**
- Create: `apps/miniapp/src/lib/skins.ts`, `apps/miniapp/src/lib/skins.test.ts`

**Interfaces:**
- Consumes: Task 1 types and `skinQueryString`.
- Produces:
  - `skinsApiParams(q: SkinQuery): string` — same mapping as web `apiParams` (`min_uzs`, `max_uzs`, `stattrak=true`, `limit=24`).
  - `fetchSkinsPage(q: SkinQuery): Promise<SkinsPage>` — throws on error (the page shows retry).
  - `fetchSkinFacets(): Promise<SkinFacets | null>` — `null` on 404 (feature off), throws otherwise.
  - `fetchSkinDetail(slug: string): Promise<SkinDetail | null>` — `null` on 404 only.
  - `fetchSkinListings(slug: string): Promise<SkinListings>`.
  - `skinPriceText(priceUzs: string | null, priceUsd: string | null): string | null`.

- [ ] **Step 1: failing tests** (fetch stubbed with `vi.stubGlobal`):

```ts
it("prints soʻm, falls back to dollars, null only without a price", () => {
  expect(skinPriceText("385700", "30.37")).toContain("385");
  expect(skinPriceText(null, "30.37")).toContain("30.37");
  expect(skinPriceText(null, null)).toBeNull();
});
it("maps the query to API params", () => {
  expect(skinsApiParams({ sort: "price", category: "rifles", minUzs: 1000, stattrak: true }))
    .toBe("category=rifles&stattrak=true&min_uzs=1000&sort=price&limit=24");
});
it("facets: null on 404 (feature off), throws on 503", async () => { /* stub 404 → null; 503 → rejects */ });
it("detail: null on 404, throws on 503", async () => { /* same */ });
```

- [ ] **Step 2:** `pnpm vitest run src/lib/skins.test.ts` — Expected: FAIL (module missing).
- [ ] **Step 3:** Implement with `apiGet(path, true)` (anonymous) and an `ApiError` 404 check; `skinPriceText` via `formatMoney(Math.round(Number(uzs)), "UZS")` / `formatMoney(Number(usd), "USD")`.
- [ ] **Step 4:** Tests PASS.
- [ ] **Step 5:** Commit `feat(miniapp/skins): API fetchers and price text`.

### Task 3: Catalogue page `/cs2-market`

**Files:**
- Modify: `apps/miniapp/src/pages/CS2SkinMarket.tsx` (the catalogue; the old "скоро" body becomes `SkinsComingSoon`)
- Create: `apps/miniapp/src/components/skins/SkinsComingSoon.tsx`, `SkinCard.tsx`, `SkinChips.tsx` (category + weapon rows), `SkinFilterSheet.tsx` (exterior, rarity, StatTrak, price from/to, sort)
- Create: `apps/miniapp/src/lib/skins-view.ts` + test — `accumulateSkins(prev, page, fromCursor)` (dedupe by slug) and `activeFilterCount(q)`
- Modify: `packages/i18n/locales/{ru,en,uz}/miniapp.json` (`cs2.*` keys)

**Behaviour:**
- Query from `useSearch()` → `parseSkinQuery(Object.fromEntries(new URLSearchParams(search)))`; every filter change `navigate("/cs2-market" + skinQueryString(q, patch), { replace: true })` so Telegram back leaves the market instead of undoing filters one by one, while item → back returns to the same URL.
- Facets load once; `null` → `SkinsComingSoon`. Page 1 loads per query; "Показать ещё" appends by `next_cursor`.
- Search input debounced 400 ms (mirrors `GiftsCatalog`), writes `q`.
- Grid 2 columns; card = image (`steamImageSize(url, "256fx256f")`), StatTrak/Souvenir, weapon, exterior, skin name, price or «Нет в наличии», discount badge when > 0, rarity colour as the bottom border.
- Weapon chips appear with a category chosen; the chosen weapon always stays on the row (web M5).

- [ ] **Step 1: failing tests** for `skins-view.ts`:

```ts
it("appends the next page and drops duplicates", () => { /* prev [a,b] + page [b,c] with cursor → [a,b,c] */ });
it("a first page replaces", () => { /* fromCursor false → page items only */ });
it("counts active filters", () => {
  expect(activeFilterCount({ sort: "popular" })).toBe(0);
  expect(activeFilterCount({ sort: "price", exterior: "FT", stattrak: true, minUzs: 1 })).toBe(3);
});
```

- [ ] **Step 2:** Run — Expected: FAIL.
- [ ] **Step 3:** Implement `skins-view.ts`, the components and the page; i18n keys.
- [ ] **Step 4:** `pnpm vitest run && pnpm exec tsc --noEmit && pnpm exec eslint src` — PASS (incl. `messages.test.ts` parity).
- [ ] **Step 5:** Commit `feat(miniapp/skins): catalogue with URL filters, search and sort`.

### Task 4: Item page `/cs2-market/:slug`

**Files:**
- Create: `apps/miniapp/src/pages/CS2Skin.tsx`, `apps/miniapp/src/components/skins/SkinListingsList.tsx`, `SkinWearRow.tsx`, `SkinFloatBar.tsx`
- Modify: `apps/miniapp/src/App.tsx` (lazy route `/cs2-market/:slug`), i18n

**Behaviour:** image (`512fx384f`), StatTrak/Souvenir + weapon, skin name + phase, exterior + rarity (coloured), price block (price text or «Нет в наличии», Steam price struck through when higher, disabled «Покупка скоро»), wear row (family > 1; tap replaces the route), offers: first 10 + «Показать ещё», each with float bar, paint seed, sticker names, «Осмотреть в игре» (inspect link via `openLink`). `null` detail → not-found text; thrown → retry.

- [ ] **Step 1: failing test** for a pure helper in `skins-view.ts`: `familyLabel(m)` → `"FT"`, `"ST · FT"`, `"SV · MW"`, and `null`-exterior → `"—"`.
- [ ] **Step 2:** FAIL. **Step 3:** implement helper + page + components. **Step 4:** full miniapp checks PASS; `pnpm build` and compare the entry chunk size against `main` (must not grow).
- [ ] **Step 5:** Commit `feat(miniapp/skins): item page with wears, float and live offers`.

### Task 5: Docs

- Modify: `docs/product/flows/skins-browse.md` (mini app section + back-button behaviour), `apps/api/src/yupay/modules/skins/README.md` (Storefront: miniapp routes), `docs/runbooks/skins-catalog.md` (launch step: mini app needs only the API flag; the Home promo card's «Скоро» badge stays until purchase ships).
- [ ] `pnpm exec prettier --check .` PASS. Commit `docs(skins): mini app storefront`.
