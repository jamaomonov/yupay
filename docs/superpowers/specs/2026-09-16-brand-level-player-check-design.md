# Design: Player check bound to the brand; MLBB and MCGG split into region brands

**Date:** 2026-09-16
**Status:** Approved in brainstorming — pending owner review of this document, then an implementation plan
**Surface:** API (`integrations`, `catalog`, `merchants`), storefront (`apps/web`, `apps/miniapp` if it shares `PurchasePanel`), catalog data on prod
**Supersedes:** ADR-0048 (two region products inside one MLBB brand) — new ADR-0079 to record it

---

## 1. Problem

The player-id check ("Проверить") is bound to a **product**: `Product.required_fields[].check` declares the provider, and `resolve_g2b_game_code(product_id)` picks the supplier game from that product's active `g2b/game` mappings. Two consequences the owner hit:

1. **A customer cannot check an id before picking a package.** `PurchasePanel` disables the check until a product is chosen on any brand with ≥2 products (`productChosen = selProduct !== undefined || products.length <= 1`). That gate exists because on MLBB the two products are two different supplier games (`mlbb`, `mlbb_ru`) and a pre-selection check would verify a Russian id against the global game. But it fires on **ten** brands, and on eight of them (PUBG, Genshin, Delta Force, …) every product is the same game — the click is pure cost.
2. **Merchants must send a `sku_id` to `POST /merchant/v1/validate/player`.** The published schema states this as a principle ("a SKU and not a product, so the id you check is the id you buy"). Every competitor's API takes a brand/game identifier. Resellers integrate against the market convention and find ours odd.

Both are the same root: the unit that maps 1:1 to a supplier game is the _product_ today, while everyone — customers, resellers, competitors — thinks in _brands_.

## 2. Facts established (prod, 2026-09-16)

- `mobile-legends` has two products: `mlbb-diamonds` (3 SKUs, G2B `mlbb`) and `mlbb-diamonds-ru` (11 SKUs, G2B `mlbb_ru`). `magic-chess-gogo` has the same shape: `mcgg-diamonds` (`magic_chess_gogo`) and `mcgg-diamonds-ru` (`mcgg_ru`).
- Every other multi-product brand maps all its products to **one** G2B game code.
- `POST /merchant/v1/validate/player`: **0 requests in 14 days**; `POST /merchant/v1/orders`: 0 in 14 days; 4 active merchants, all internal. No live integrator depends on `sku_id`.
- Reviews (`reviews.models`) are keyed by **brand**. Merchant Center feed offers are keyed by `sku_code`; the offer title carries the brand name.
- The admin `ProductUpdate` already accepts `brand_id`, so a product can move between brands without schema work.
- The owner confirms customers generally know whether their account is Russian or global. Auto-detecting the region (checking both games) was considered and set aside on that basis.

## 3. Decision drivers

- One mental model for everyone: a brand is one game.
- The check must stay **advisory and never a fake rejecter** (ADR-0031 and its amendments): two supplier games behind one brand must produce _no check_, never a wrong one.
- Zero breaking change for anything with live traffic; a clean contract where there is none.
- SEO: `mobile-legends` keeps its slug and page.

## 4. Options considered

- **A. Split MLBB and MCGG into region brands; bind the check to the brand.** Chosen.
- **B. Keep one brand, bind the check to brand + region.** Not a real option: without a region the brand does not name a game, so this is A or C in disguise.
- **C. Keep the catalog; probe every game code behind a brand and return which product matched (auto-detect region).** Better UX for a customer who does not know their region; more code, two supplier calls per check on region brands, an ambiguity edge when an id exists in both games. Set aside because customers know their region and the owner prefers the explicit model.

## 5. Design

### 5.1 The invariant: a brand is exactly one supplier game

`integrations.player_check` gains a brand-scoped resolver, replacing the product-scoped one:

- `resolve_g2b_game_code(session, brand_id)` collects `external_product_id` over the active `g2b/game` mappings of **all** SKUs of **all** products of the brand. Exactly one distinct code → that code. Zero → no check (`player_check_no_game_mapping`, as today). Two or more → **no check** plus a `player_check_brand_spans_games` warning naming the brand and the codes. Never pick one.
- The `check` declaration stays on `Product.required_fields` — moving `required_fields` to the brand would touch orders validation, the admin product editor and the storefront form for no gain. The brand's check config is read from its **first checkable product**; if two checkable products of one brand disagree on `provider`, `server_field` or the field key, that is the same misconfiguration → no check + warning.
- Waxpeer (Steam) is unaffected: its check needs no game code.

### 5.2 Catalog: the split

One idempotent operator seed, `scripts/seed/2026-09-16_region_brands.sql`, applied to prod **before** the code deploy (see §6):

- New brand `mobile-legends-ru`: same category, logo, hero, accent, `visible_b2b` (currently `true`), `sort_order` right after `mobile-legends`; translations "Mobile Legends RU" in ru/en/uz. Product `mlbb-diamonds-ru` moves to it (`products.brand_id`). SKUs, mappings, sourcing rules are per SKU and do not move.
- New brand `magic-chess-gogo-ru` the same way; `mcgg-diamonds-ru` moves to it. Translations "Magic Chess: Go Go RU".
- `mobile-legends` and `magic-chess-gogo` keep their slugs, pages and reviews.
- Brand content for all four pages (`short_description`, `description`, `instructions`, `highlights`, FAQs): the region question moves from "which package" to "which brand" — the first FAQ on each page is "Российский или глобальный аккаунт — как понять?" with a link to the sibling brand. Existing MLBB/MCGG FAQ that explain the two-products layout are rewritten.
- Blog: `blog_post_brands` gets the RU brand added to the existing MLBB guide so it shows on both pages. `primary_brand_id` stays.
- Downstream that picks the change up with no work: sitemap, `llms.txt`, `/md`, merchant catalog (`GET /merchant/v1/catalog` lists brands), storefront catalog grid. The Merchant Center feed will _update_ RU offers' titles on its next hourly push (offerId is `sku_code`, so nothing is deleted).
- Verified on the dev DB before prod: apply, re-apply (no-op), and the storefront renders four brand pages.

### 5.3 The check endpoint and the storefront

- **New:** `POST /api/v1/catalog/brands/{slug}/check-player`, body `PlayerCheckIn` (`player_id`, `server_id`), response `PlayerCheckOut` — unchanged shapes. Resolves through §5.1. Same advisory rules, breaker, rate bucket and positive-only cache as today; cache key gains the brand: `playercheck:g2b:{game_code}:{server|-}:{player_id_hash}` is already per game, so no key change is needed.
- **Removed in the same release:** `POST /api/v1/catalog/products/{product_id}/check-player`. Its only caller is our storefront, which ships in the same deploy. AGENTS.md §9's list of keyless advisory POSTs is updated to name the brand endpoint.
- **Storefront (`PurchasePanel`, `player-check-state.ts`):** the check is available **before** a package is chosen on every brand — the `productChosen` gate is removed. Verdicts are keyed by `brandId` instead of `productId` and survive a package change within the brand; the ADR-0048 cross-product invalidation is deleted. A verdict never survives navigation to another brand (different page, different state — nothing to do). The cost the gate was protecting against no longer exists: a brand is one game.
- The miniapp shares this component if it imports `PurchasePanel`; verify during implementation and apply the same change.

### 5.4 The merchant contract

- `POST /merchant/v1/validate/player` body becomes `{brand: <slug>, player_id, server_id?}`. `sku_id` is **removed** (0 live traffic; `extra="forbid"` will reject it with a 422 that names the new field).
- Visibility rule keeps its spirit: the brand must be `visible_b2b` and must have at least one SKU visible to B2B; otherwise `unsupported` — the same answer a withheld SKU gives today.
- Response unchanged.
- Docs: `docs/api/README.md` §validate/player, `docs/runbooks/merchant-b2b.md`, the machine OpenAPI (`docs/api/merchant-openapi.json`, regenerated) and the published Swagger. The "SKU, not product" principle is replaced with: "a brand, because a brand is one game; the SKU you then order belongs to it".

### 5.5 Guarding the region choice, now at brand level

ADR-0048's three guard layers assumed one page. Replacements:

1. Both brand cards sit adjacent in the catalog grid (`sort_order`), named unambiguously ("Mobile Legends" / "Mobile Legends RU").
2. Each brand page shows a **sibling-region link** near the id field: "Аккаунт российский? → Mobile Legends RU" and the mirror. Data-driven: a small `region_sibling_slug` on `brand_translations`? No — that is a schema change for two brands. It is content: a highlighted line in `instructions`/FAQ plus a storefront rule that renders the link when the brand slug ends in `-ru` or a sibling `<slug>-ru` exists in the catalog list the page already fetched. No new column.
3. An `invalid` verdict on a region brand renders the hint "Не найден. Если аккаунт другого региона — проверьте на <sibling>" — the one place the customer learns about the split at the moment it matters.

### 5.6 Admin and observability

- `integrations` mapping upsert does **not** refuse a second game code on a brand (it would block re-mapping mid-migration). The resolver's `player_check_brand_spans_games` warning is the signal; the supplier detail page shows a banner for any brand whose active `g2b/game` mappings span two codes, listing them. Cheap query, runs on page load.

## 6. Rollout order

1. **Seed first, code second.** Today's code checks per product and does not care which brand a product sits in, so the data split is safe on the current release. The reverse order would leave MLBB without a check between deploy and seed (brand-scoped resolver sees two codes).
2. Apply the seed on prod; confirm four brand pages render via ISR; confirm merchant catalog lists four brands.
3. Deploy the release: brand endpoint, storefront, merchant contract, product endpoint removed.
4. Verify on prod: check before package selection on `mobile-legends`, `mobile-legends-ru`, `pubg-mobile`; `validate/player` with `brand`; old product endpoint → 404.

## 7. Testing

- **API integration:** brand with one game → check answers; brand spanning two codes → `error` + warning; brand with no mapping → `error` (existing behaviour); merchant `validate/player` with `brand` (visible / withheld / unknown → 422); `sku_id` in the body → 422.
- **Seed:** applied twice on the dev DB, second run changes nothing; product counts per brand as expected; slugs unchanged for the globals.
- **Storefront vitest:** check button enabled before package selection on a multi-product brand; verdict survives package change; sibling-region link renders on both MLBB pages and on no other brand; `invalid` on a region brand shows the sibling hint.
- **Docs check:** `openapi-drift` and `docs-check` in CI; merchant OpenAPI regenerated.

## 8. Documents

- ADR-0079 "Region brands and the brand-level player check" — supersedes ADR-0048; amends ADR-0031's endpoint list.
- `docs/architecture/module-map.md` (integrations public surface), `docs/api/README.md`, `docs/runbooks/merchant-b2b.md`, `apps/api/src/yupay/modules/integrations/README.md`, AGENTS.md §9 keyless-POST list.

## 9. Non-goals

- Auto-detecting the region (option C). Revisit if support tickets show customers guessing wrong.
- Moving `required_fields`/`check` from product to brand.
- Any change to ordering, sourcing, fulfilment or the Steam/Waxpeer check.
- A deprecation window for `sku_id` on the merchant endpoint — there is nothing to deprecate for.

## 10. Decisions taken in brainstorming

- Split both MLBB and MCGG (same shape, same fix).
- RU brand names: "Mobile Legends RU", "Magic Chess: Go Go RU"; slugs `mobile-legends-ru`, `magic-chess-gogo-ru`.
- `sku_id` removed from `validate/player`, not dual-moded.
- Product-level public endpoint removed in the same release.
