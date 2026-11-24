# 0099. A game's regions are brands linked to its main brand

- **Status**: Accepted
- **Date**: 2026-10-16
- **Deciders**: owner, Claude
- **Tags**: backend | frontend | data
- **Amends**: [ADR-0079](./0079-region-brands-and-brand-level-player-check.md)

## Context and problem statement

ADR-0079 made each region of a game its own brand (a brand is one supplier
game) and paired the two regions we sold by slug, `<slug>` ↔ `<slug>-ru`,
noting that a third pair would call for a column. The owner now wants every
region we can source on the storefront: Mobile Legends in Russia, the
Philippines, Malaysia, Singapore, Indonesia, Turkey, the US and Brazil, and
Magic Chess: Go Go in Russia, Malaysia, the Philippines and Turkey, and Free
Fire's global server and twelve regional ones. These
brands already exist from the bulk supplier import, priced and B2B-only.

## Decision outcome

- `brands.region_parent_id` names the game's main brand and
  `brands.region_code` the region (`ru`, `ph`…). A region must name its code;
  on a main brand the code is optional and NULL reads as `global`. Free
  Fire's main brand is the CIS server (`cis`), and the global server is one
  of its regions. The main brand is always first on the switcher. Migration
  `0101_brand_regions` links the brands above by slug.
- The retail brand list leaves regional brands out. `GET /catalog/brands/{slug}`
  returns `region_code` (`global` on a main brand without one), `region_of` (the main
  slug, on a region) and `regions`: every active, retail-visible brand of the
  game in switcher order. The list is empty when only one region is sellable.
- A region shows on the storefront while its brand is `visible_retail`, which
  is also the gate for its page data, player check and checkout. Switching a
  region off is switching its brand off.
- Web has one page per game, `/store/<main>`, with a region switcher;
  `/store/<region slug>` redirects to `/store/<main>?region=<code>`. The Mini
  App has one card per game and the same switcher. The page talks to the
  picked region's brand for products, the player check and the order.
- Reviews belong to the game: a review from a regional order is filed under
  the main brand (`reviews.service.resolve_brand_id`), and the migration moved
  the existing ones and rebuilt the affected stats.
- The Merchant Center feed links a regional SKU to `/store/<main>?region=<code>`.
- The merchant (B2B) catalogue and API ignore the link: regions stay separate
  brands there, so integrations need no change.
- A region whose products declare no player check (MLBB in the Philippines,
  Malaysia, Singapore and Indonesia, Free Fire in the Philippines and
  Thailand — no supplier validates them for us) is sold
  unchecked, with a hint on the page to make sure the account is in that
  region.

## Consequences

- The `-ru` slug convention and its helpers (`region-sibling.ts`, the Mini
  App's `-ru` logic) are gone; nothing infers a region from a slug.
- Adding a region is data: create or import the brand, set the two columns,
  make it `visible_retail`.
- Exclusive and Special MLBB catalogues are not regions and stay unlinked.

## Later additions

- **2026-11-24 — Roblox.** The 25 imported `roblox-xx` gift-card brands became
  regions of `roblox` (seed `scripts/seed/2026-11-24_roblox_regions.sql`), with
  seventeen new region codes (`uk`, `ca`, `au`, `nz`, `jp`, `hk`, `ae`, `sa`,
  `mx`, `za`, `fr`, `at`, `ch`, `dk`, `no`, `se`, `pl`) added to `REGION_ORDER`
  and the web and Mini App switcher labels. Codes need no player check, so no
  "unchecked" hint shows.
- **2026-11-24 — PlayStation, Xbox, Nintendo eShop, App Store & iTunes, Google
  Play.** These have no global card, only country brands (122 of them, from
  the import). Each gets a **main brand that sells nothing itself**
  (`playstation`, `xbox`, `nintendo`, `app-store`, `google-play`, seed
  `scripts/seed/2026-11-24_platform_gift_card_regions.sql`). Such a main
  brand's `region_code` names the region its page opens on: the API leaves the
  main brand off `regions`, lists that region first (even when it is the only
  one), and answers the main brand's `products` with that region's
  (`catalog.service._products_on_page`), so web, Mini App and the mobile app
  read the page like any other. Purchases still name the region's SKU.
  Twenty-four more codes were added to `REGION_ORDER` and the labels. The Mini
  App resolves the brand to talk to from every listed region, not just the
  chips, so a one-region platform still lands on its region.
- **2026-11-24 — Steam Wallet codes.** `steam-wallet` (global USD codes) and
  its 28 country brands (seed `scripts/seed/2026-11-24_steam_wallet_regions.sql`).
  The main brand's code is `usd` («Глобальная (USD)»), not `global`, so its
  chip does not claim to suit Uzbek accounts; the page's FAQ sends those to the
  login top-up (`steam`). New codes: `cl`, `pe`, `uy`, `cr`, `usd`.
