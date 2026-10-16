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
