/**
 * Several fixed packs in one order — «110 алмазов × 3 + 341 алмазов» paid once
 * (2026-10-31). The panel keeps how many of each pack the buyer picked; the
 * order carries every piece as its own `qty: 1` line, because one supplier
 * call buys one pack (FazerCards refuses `qty > 1` on a top-up) and a line of
 * its own is what lets one failed piece be retried or refunded alone.
 */

/** The API takes at most 20 lines an order (`OrderCreate.items`). */
export const CART_MAX_UNITS = 20;

/** Pack SKU id → how many. Absent means none. */
export type PackCounts = Readonly<Record<string, number>>;

export function cartUnits(counts: PackCounts): number {
  return Object.values(counts).reduce((n, c) => n + c, 0);
}

/**
 * Puts one of a pack into the order. Packs of another product start a new
 * order instead: a brand's products may ask for different account fields,
 * and one form fills every line.
 */
export function addPack(counts: PackCounts, skuId: string, sameProduct: boolean): PackCounts {
  const base = sameProduct ? counts : {};
  if ((base[skuId] ?? 0) > 0 || cartUnits(base) >= CART_MAX_UNITS) return base;
  return { ...base, [skuId]: 1 };
}

/** One more (`+1`) or one fewer (`-1`); a pack that reaches zero leaves the order. */
export function stepPack(counts: PackCounts, skuId: string, delta: 1 | -1): PackCounts {
  const n = (counts[skuId] ?? 0) + delta;
  if (delta > 0 && cartUnits(counts) >= CART_MAX_UNITS) return counts;
  if (n <= 0) return Object.fromEntries(Object.entries(counts).filter(([id]) => id !== skuId));
  return { ...counts, [skuId]: n };
}

/** Every piece as its own order line, packs in the order given. */
export function expandPieces<T>(
  lines: readonly { skuId: string; count: number }[],
  line: (skuId: string) => T,
): T[] {
  return lines.flatMap(({ skuId, count }) => Array.from({ length: count }, () => line(skuId)));
}
