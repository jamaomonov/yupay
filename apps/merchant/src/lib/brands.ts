/**
 * How big the wholesale catalogue is, as the public site states it.
 *
 * Static on purpose. The site used to count `GET /api/v1/catalog/brands`,
 * which is the **retail** storefront list (28 brands) — the reseller-only
 * imports never appear there, so the hero undersold the catalogue roughly
 * thirtyfold. There is no public endpoint for the B2B count, and a landing
 * should not call a private one.
 *
 * Measured on production on 2026-11-11: 878 brands and 10 667 SKUs available
 * to resellers. The figures are rounded **down** so they stay true while the
 * catalogue shrinks a little; re-measure and edit them when it moves by a
 * round step.
 */
export const CATALOG_BRANDS = 870;

/** SKUs available to resellers — see {@link CATALOG_BRANDS} for the date and source. */
export const CATALOG_SKUS = 10_000;

/** `870` → «870», `10000` → «10 000» / «10,000», in the reader's locale. */
export function formatCount(locale: string, value: number): string {
  return new Intl.NumberFormat(locale).format(value);
}
