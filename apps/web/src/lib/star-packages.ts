/**
 * Telegram Stars package tiers, shown as quick-pick tiles above the free-typed
 * quantity field on a unit SKU (`min_qty`/`max_qty` set, `variable_amount`
 * false — see `yupay.modules.catalog.unit_sku.is_unit_sku` on the server).
 *
 * Mirrored verbatim into `apps/miniapp/src/lib/star-packages.ts` (Task 8) —
 * the two storefronts don't share a workspace package for pure logic (see
 * `variable-amount.ts` in each app for the same precedent), so keep both
 * copies in sync when this file changes. The list is a working set; a final
 * release only needs a one-line edit here.
 */

/** Candidate Stars pack sizes, largest-inclusive. An admin's `min_qty`/
 *  `max_qty` on the SKU narrows this down per product — see
 *  `visibleStarPackages`. */
export const STAR_PACKAGES = [
  50, 75, 100, 150, 250, 350, 500, 750, 1000, 1500, 2500, 5000,
] as const;

/**
 * The packs a customer is actually allowed to tap, given the SKU's
 * admin-configured bounds. Both ends are inclusive, matching the server's own
 * closed-interval check (`unit_sku.assert_qty_allowed`).
 */
export function visibleStarPackages(min: number, max: number): number[] {
  return STAR_PACKAGES.filter((n) => n >= min && n <= max);
}

/** How many star copies a pack's thumbnail stacks. Front-most is index 0. */
export const MAX_STAR_LAYERS = 4;

/**
 * How many copies of the star to pile up for a pack of `units`.
 *
 * The tiles all carried the same single star, so the only thing separating a
 * 50-pack from a 5000-pack was the number underneath it — the art said
 * nothing. Stacking the *same* image behind itself turns the thumbnail into a
 * second reading of the size, at a glance and without a second asset.
 *
 * Thresholds are magnitude boundaries, not the list's index — indexing would
 * re-rank every tile the moment a pack is added or removed. They also spread
 * the current twelve packs 2/4/4/2 across the four piles rather than piling
 * half of them onto one step, so neighbouring tiles usually differ.
 */
export function starLayers(units: number): number {
  if (units >= 2500) return 4;
  if (units >= 500) return 3;
  if (units >= 100) return 2;
  return 1;
}

/**
 * What a pack of `units` costs, in the currency `unitDisplayPrice` (the
 * SKU's `display_price`, already an FX conversion or override) is quoted in.
 * A unit SKU has one flat per-unit rate — no volume-discount bands like
 * `tierPrice`'s packages — so this is exactly `units * unitDisplayPrice`,
 * never a guessed or rounded rate.
 */
export function packagePrice(units: number, unitDisplayPrice: number): number {
  return units * unitDisplayPrice;
}
