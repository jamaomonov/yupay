# CS2 Skins — Storefront Polish (plan 2c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Act on the 2026-09-28 design review of both skins storefronts (web `/skins`, mini
app `/cs2-market`): category icons, one honest price on the item page, a wear picker people
understand, offers that read at a glance, a phone-friendly web filter panel, and the site
header at tablet width. The owner asked for all of it («го делаем все»).

**Architecture:** One API change — `/skins/facets` takes an optional `category` and scopes
every facet to it (so the weapon row lists the whole category, and wear/rarity counts match
the grid), and rarities carry their colour. Everything else is frontend. Category icons are
ten Steam item images self-hosted as PNGs in both apps' `public/` (Steam's CDN sends no CORS
header, so a cross-origin `mask-image` does not render) and drawn as a `currentColor`
silhouette via CSS `mask-image`.

**Spec:** `docs/superpowers/specs/2026-09-28-cs2-skins-design.md`; review findings live in this
plan's Rulings and the session.

## Global Constraints

- Read-only storefront; purchase is plan 3. No service meta in copy; nothing Waxpeer-branded.
- Web/miniapp i18n in ru/en/uz in the same commit.
- Rarity names stay English (the game's and skinsavdo.uz's labels), shown only when present in
  the chosen category, each with its colour dot.
- Default sort becomes `-price` («Сначала дороже») — skinsavdo.uz opens the same way; `popular`
  opened on a wall of cases and capsules.
- Bundle: web route ≤ 180 KB, mini app pages stay lazy chunks.

## Review Focus

1. Category change → weapon row lists every weapon of the category, AK-47/M4A4/M4A1-S/AWP first.
2. Item page: the headline price equals the cheapest offer shown below once offers load.
3. A case/key/agent/music kit page shows no wear picker and no per-offer list of identical rows.
4. Web at 390 px: filters open in a bottom drawer, grid stays on screen; the active category chip is scrolled into view.
5. Web header at 768 px: no overlap; nav collapses to the burger below `lg`.

---

### Task 1: Scoped facets (API)

- `GET /skins/facets?category=<slug>`: categories stay global (the tile row); weapons, exteriors,
  rarities are counted within the category when given. Weapons ordered by a fixed priority
  (`AK-47, M4A4, M4A1-S, AWP, Desert Eagle, USP-S, Glock-18`) then by count. Rarity facet gains
  `color`. Cache key gains the category. Unknown category → 422 via the existing slug enum.
- Tests (integration): weapons of `rifles` include one only present beyond page 1; exterior
  counts scoped; rarity colour present; priority order.
- Regenerate `docs/api/openapi.json`; `docs/architecture/cache-keys.md`.

### Task 2: Shared frontend model (`@yupay/utils`)

- `DEFAULT_SORT = "-price"`; `Facet` gains optional `color`.
- `CATEGORY_ICONS: Record<SkinCategory, { file: string; wide: boolean } | null>` (music kits → null).
- `offerHeadline(stored, offers)` → the cheapest offer's `{uzs, usd}` when offers exist, else the stored price.
- `wearChoices(family, current)` → `{ wears: {exterior, slug|null}[], stattrak: slug|null, souvenir: slug|null }`
  choosing, for each wear, the twin with the current StatTrak/Souvenir state.
- Tests for both helpers + the sort default.

### Task 3: Category icons (both apps)

- `scripts/skins/fetch-category-icons.sh` downloads the ten `/96fx96f` PNGs into
  `apps/web/public/skins/categories/` and `apps/miniapp/public/skins/categories/`.
- `SkinCategoryTiles` (web: 12-column tiles ≥ lg, scrolling tiles below; mini app: scrolling
  tiles 60 px): silhouette `bg-current` masked, grey idle, primary when active; «Все» uses
  `LayoutGrid`, «Музыка» uses `Music`. Active tile scrolled into view on mount.
- Weapon row reads the scoped facets.

### Task 4: Catalogue polish

- Web: mobile filters in a bottom drawer (client island wrapping the server filter panel, «Готово»
  closes), desktop sidebar unchanged; rarity list with colour dots from scoped facets.
- Both: empty state with icon + «Сбросить фильтры»; card price `tabular-nums` (no mono);
  discount badge only ≥ 5 %; web card drops «×count».
- Mini app sheet: StatTrak as a switch, no lime ring on close, rarity after price.

### Task 5: Item page

- Headline price = cheapest live offer (shared state between price block and offers); before
  offers load or without offers: stored price prefixed «от». Steam price link on its own muted line.
- Buy button neutral (`bg-surface-2`, muted text) while purchase is not live.
- Wear picker: segmented wears (full names on web, short on mini app) + StatTrak™/Souvenir
  toggles; wears without a row or without offers greyed.
- Items without wear (no exterior): no offers list; «В наличии: N шт.» instead.
- Offer row: price first, float bar, sticker thumbnails (20 px, name as title/aria-label);
  «Мгновенно» shown once by the price as «Мгновенная доставка», not per row.
- Vanilla knives/gloves: title «Vanilla» (ru «Ванильный», uz «Vanilla»), not the weapon twice.
- Web breadcrumb uses the translated category; web hero shows facts (float range, rarity,
  offers count) under the CTA. Offers skeleton sized to real rows.
- Mini app wear prices never wrap (`whitespace-nowrap`, compact format ≥ 1 000 000).

### Task 6: Web header at tablet width

- `PrimaryNav` and the right cluster from `md:` to `lg:`; `MobileNav` to `lg:hidden`.

### Task 7: Docs + checks

- `docs/product/flows/skins-browse.md` (icons, default sort, drawer, price rule), module README,
  `prettier --check .`, web + miniapp + API skins suites, screenshots re-checked at 1440/768/390/360.
