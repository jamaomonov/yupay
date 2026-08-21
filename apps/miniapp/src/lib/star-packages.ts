/**
 * Telegram Stars package tiers, shown as quick-pick tiles above the free-typed
 * quantity field on a unit SKU (`min_qty`/`max_qty` set, `variable_amount`
 * false — see `yupay.modules.catalog.unit_sku.is_unit_sku` on the server).
 *
 * Mirrored verbatim from `apps/web/src/lib/star-packages.ts` (Task 7) — the
 * two storefronts don't share a workspace package for pure logic (see
 * `variable-amount.ts` in each app for the same precedent), so keep both
 * copies in sync when this file changes. The list is a working set; a final
 * release only needs a one-line edit here.
 */

/** Candidate Stars pack sizes, largest-inclusive. An admin's `min_qty`/
 *  `max_qty` on the SKU narrows this down per product — see
 *  `visibleStarPackages`. */
export const STAR_PACKAGES = [50, 75, 100, 150, 250, 350, 500, 750, 1000, 1500, 2500] as const;

/**
 * The packs a customer is actually allowed to tap, given the SKU's
 * admin-configured bounds. Both ends are inclusive, matching the server's own
 * closed-interval check (`unit_sku.assert_qty_allowed`).
 */
export function visibleStarPackages(min: number, max: number): number[] {
  return STAR_PACKAGES.filter((n) => n >= min && n <= max);
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
