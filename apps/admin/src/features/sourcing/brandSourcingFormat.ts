/** Pure display helpers for the brand-overview screen — split out of
 *  `BrandSourcingTable.tsx` to keep that file under the 300-LOC soft limit.
 *  Nothing here does I/O or touches component state. */

import type { SourcingBrandSupplierOut } from "./types";

import { SUPPLIER_LABELS, type KnownSupplier } from "@/features/integrations/types";

/** Best-effort human label for a supplier slug — a `switch` over the known
 *  set rather than indexing `SUPPLIER_LABELS` with a bare `string` (which
 *  `Record<KnownSupplier, string>` correctly refuses without narrowing
 *  first, and this project's rules bar an `as` cast for anything short of
 *  a known-shape JSON/DOM narrowing). */
export function supplierLabel(slug: string): string {
  const known: readonly KnownSupplier[] = ["g2b", "waxpeer", "gengine", "nova"];
  const match = known.find((k) => k === slug);
  return match ? SUPPLIER_LABELS[match] : slug;
}

/** Human description of `SourcingBrandSkuOut.primary` — mirrors the shape
 *  of `sourcing.service.Decision.primary`: `"inventory"`,
 *  `"supplier:<slug>"` (including the non-supplier `"supplier:manual"`
 *  sentinel), or `"invalid"` for a malformed rule the backend still
 *  reports rather than 500s on. */
export function describeRoute(primary: string): string {
  if (primary === "inventory") return "Склад кодов";
  if (primary === "invalid") return "Некорректное правило";
  if (primary === "supplier:manual") return "Ручная выдача";
  if (primary.startsWith("supplier:")) {
    const slug = primary.slice("supplier:".length);
    return `Поставщик ${supplierLabel(slug)}`;
  }
  return primary;
}

/** Margin `price_usd` implies over `cost_usdt` — display only, never fed
 *  back into a request: `Number.parseFloat` on a money string is the same
 *  display-comparison precedent `SkuPriceHistoryCard`/`SkuPriceHistoryModal`
 *  already use for these same two fields. */
export function marginPercent(priceUsd: string, costUsdt: string | null): string | null {
  if (costUsdt === null) return null;
  const price = Number.parseFloat(priceUsd);
  const cost = Number.parseFloat(costUsdt);
  if (!Number.isFinite(price) || !Number.isFinite(cost) || price <= 0) return null;
  return (((price - cost) / price) * 100).toFixed(1);
}

/** Which supplier is cheapest for this row, among suppliers that are both
 *  actively mapped and have a recorded cost — display-only comparison,
 *  same precedent as `marginPercent` above. */
export function cheapestSlug(suppliers: SourcingBrandSupplierOut[]): string | null {
  let best: { slug: string; value: number } | null = null;
  for (const s of suppliers) {
    if (!s.has_active_mapping || s.latest_cost_usdt === null) continue;
    const value = Number.parseFloat(s.latest_cost_usdt);
    if (!Number.isFinite(value)) continue;
    if (best === null || value < best.value) best = { slug: s.supplier_slug, value };
  }
  return best?.slug ?? null;
}
