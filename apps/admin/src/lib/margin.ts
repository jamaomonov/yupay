/**
 * Shared margin formula for the admin SPA.
 *
 * The system's one definition of "margin" is `price_usd = cost_usdt * (1 +
 * margin_percent / 100)` — `Sku.margin_percent`'s contract in
 * `apps/api/src/yupay/modules/catalog/models.py`, which the hourly supplier
 * price-refresh job re-derives `price_usd` from. Solved for margin, that is
 * `(price - cost) / cost * 100` — **cost** is the denominator, not price.
 *
 * Every screen that shows or edits a margin number must compute it this one
 * way. Two screens (`catalog/skus/SkuEditPage.tsx` and
 * `sourcing/BrandSourcingTable.tsx`) used to each carry their own copy, and
 * the sourcing one had drifted to divide by price instead of cost — same
 * SKU, two different numbers under the same word. Import this instead of
 * reimplementing the arithmetic.
 */

/**
 * Margin `price` implies over `cost`, rounded to 2 decimals — matches the
 * sell-price formula the G2B import wizard uses (`DenominationTable.sellPrice`),
 * solved for the other variable. Returns `""` whenever either input is
 * missing/non-numeric or `cost <= 0` (a zero/negative cost can't anchor a
 * percentage), so a half-typed cost or price never freezes a stale margin on
 * screen — callers that want `null` instead of `""` (a display-only context
 * with no form field to leave untouched) can map it themselves.
 * `Math.round(...) / 100` drops floating-point noise (e.g. 19.999999999998)
 * before it's shown.
 */
export function marginFromCostAndPrice(
  costStr: string | null | undefined,
  priceStr: string | null | undefined,
): string {
  const cost = Number.parseFloat(costStr ?? "");
  const price = Number.parseFloat(priceStr ?? "");
  if (Number.isNaN(cost) || cost <= 0 || Number.isNaN(price)) return "";
  const margin = Math.round(((price - cost) / cost) * 100 * 100) / 100;
  return margin.toString();
}

/**
 * «По факту 23,7%» when the saved price sits off the target margin by half a
 * point or more, else null. The field shows the target, and until 2026-11-13
 * the hourly refresh never lowered a price, so a SKU could read «10%» while
 * selling at 23.7% — the owner found one by eye.
 */
export function actualMarginNote(
  targetStr: string | null | undefined,
  costStr: string | null | undefined,
  priceStr: string | null | undefined,
): string | null {
  const target = Number.parseFloat(targetStr ?? "");
  const actual = Number.parseFloat(marginFromCostAndPrice(costStr, priceStr));
  if (Number.isNaN(target) || Number.isNaN(actual)) return null;
  if (Math.abs(actual - target) < 0.5) return null;
  const pct = actual.toLocaleString("ru-RU", { maximumFractionDigits: 1 });
  return `По факту ${pct}% — цена ${actual > target ? "выше" : "ниже"} цели.`;
}
