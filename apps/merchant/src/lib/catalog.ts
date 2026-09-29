import type { Brand, Sku } from "./types";

/**
 * The one thing a brand sells, when it sells exactly one — Steam's «any amount», Telegram
 * Stars. There is nothing to choose, so the brand page opens with it picked rather than
 * making the reseller tap the only card there is.
 */
export function soleSku(brand: Brand): Sku | null {
  const skus = brand.products.flatMap((p) => p.skus);
  return skus.length === 1 ? (skus[0] ?? null) : null;
}
