# 0079. Region brands, and a player check bound to the brand

- **Status**: Accepted
- **Date**: 2026-09-16
- **Deciders**: owner, Claude
- **Tags**: backend | frontend | data
- **Supersedes**: [ADR-0048](./0048-mobile-legends-region-split.md)

## Context and problem statement

The player-id check was bound to a product, because Mobile Legends (and Magic
Chess: Go Go) sold two regions — two supplier games — as two products of one
brand (ADR-0048). Consequences: the storefront could not check an id before a
package was picked on any brand with more than one product (ten brands, eight
of which are one game); the reseller API took a `sku_id` where every
competitor takes a brand; and "which unit is one game" was answered
differently by customers (the brand), the catalog (the product) and G2B (the
game code).

## Decision drivers

- One mental model: a brand is one game.
- The check must never guess (ADR-0031): two games behind one brand → no check.
- Customers know their region (owner, from support); the split moves the
  choice to the catalog, where names carry it.
- `POST /merchant/v1/validate/player` had zero traffic in 14 days.

## Considered options

1. **Split MLBB and MCGG into global + RU brands; bind the check to the brand.**
2. Keep one brand; bind the check to brand + region — not an option without a
   region, which is a product choice by another name.
3. Keep the catalog; probe every game behind a brand and report which matched.
   Better for a customer who does not know their region; more code and two
   supplier calls per check. Set aside because customers do know.

## Decision outcome

Option 1. `mobile-legends-ru` and `magic-chess-gogo-ru` exist; the global
slugs are unchanged. `resolve_g2b_game_code` is brand-scoped and refuses on
two codes (`player_check_brand_spans_games`). Public
`POST /catalog/brands/{slug}/check-player` replaces the product route;
`validate/player` takes `brand`. The storefront checks before a package is
picked and keys verdicts by brand; the two split brands link to each other
and point a not-found id at the sibling.

Rollout: seed first, code second — the product-scoped check did not read the
brand, so the data split was safe on the old release, while the new resolver
on the old data would have refused MLBB.

The two brands pair up by a slug convention, `<slug>` ↔ `<slug>-ru`
(`apps/web/src/lib/region-sibling.ts`), not a column — two pairs do not
justify a schema. The risk that trade accepts: an unrelated future brand
whose slug happens to end in `-ru`, whose stripped prefix happens to match
another real brand's slug, would link to it as if it were that brand's
region sibling. Accepted for two pairs; revisit with a column if a third
pair, or a near-miss, shows up.

## Consequences

- Reviews stay with the global brands; the RU brands start at zero.
- Merchant Center feed titles of RU SKUs change (offerId is `sku_code`, so
  nothing is deleted).
- A future two-game brand fails loudly (`error` + log) instead of quietly
  checking the wrong game.

## Declined

The spec's §5.6 admin banner — the supplier detail page listing any brand
whose active `g2b/game` mappings span two codes — was declined by the owner
on 2026-09-17 after the release shipped: no such brand exists on prod, and
the case only arises from a mistaken mapping edit. The signals for a brand
mid-split (or simply misconfigured) remain: the `player_check_brand_spans_games` and
`player_check_brand_config_mismatch` warnings logged by
`integrations/player_check.py`, and the pre-seed SQL checks in
`docs/superpowers/plans/2026-09-16-brand-level-player-check.md`'s Rollout
step 0.

## Validation

- `apps/api/tests/unit/test_player_check_service.py` and
  `apps/api/tests/integration/test_player_check_endpoint.py`: a one-game
  brand answers the check; `test_a_brand_spanning_two_games_checks_nothing`
  covers the two-code refusal (`player_check_brand_spans_games`);
  `test_a_retired_product_s_mapping_does_not_block_the_live_one` covers the
  active-products-only scan; `test_brand_check_fields_must_agree_across_products`
  covers a brand whose products disagree on their `check` config
  (`player_check_brand_config_mismatch`, not checkable).
- `apps/api/tests/integration/test_merchant_validate.py` and
  `apps/api/tests/unit/test_machine_schemas.py`: `validate/player {brand}`
  happy path; `unknown_brand` / `not_b2b_visible` refusals keyed `brand`
  (`unavailable_brand` in `merchants/quote.py`); `sku_id` in the body → 422
  (`extra="forbid"`); visibility mirrors `/catalog` exactly — `visible_b2b`
  only, no active-chain filter.
- `apps/web/src/components/store/PurchasePanel.test.tsx`: the check is
  enabled before a package is picked on a multi-product brand; a confirmed
  nickname survives a same-brand package switch; a not-found id gets a hint
  pointing at the sibling brand, given one. It does not pin where the
  always-visible sibling link renders — that link is on the (server
  component) brand page, not the panel, so it has no component test.
- `apps/web/src/lib/region-sibling.test.ts`: the `<slug>` ↔ `<slug>-ru`
  pairing itself — both directions, and `null` for a brand with no sibling.
- `apps/miniapp/src/lib/player-check-state.test.ts`: the brand-keyed verdict,
  mirroring web.
- `scripts/seed/2026-09-16_region_brands.sql`: applied and re-applied against
  the dev DB, the second run a no-op; the four brand pages render. Not yet
  run on prod — that is the operator rollout, pending the owner's go.

## References

- Spec: `docs/superpowers/specs/2026-09-16-brand-level-player-check-design.md`
- ADR-0031, ADR-0048
