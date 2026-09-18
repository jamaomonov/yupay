/** Pure display helpers for the brand-overview screen — split out of
 *  `BrandSourcingTable.tsx` to keep that file under the 300-LOC soft limit.
 *  Nothing here does I/O or touches component state. */

import type { SourcingBrandSupplierOut } from "./types";

import { SUPPLIER_LABELS, type KnownSupplier } from "@/features/integrations/types";
import { marginFromCostAndPrice } from "@/lib/margin";

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
 *  back into a request. Delegates to the one shared formula
 *  (`marginFromCostAndPrice`, `@/lib/margin`) so this screen can never show a
 *  different number than the SKU editor for the same SKU under the same
 *  word; only the display rounding (1 decimal, `null` instead of `""`) is
 *  local to this screen. */
export function marginPercent(priceUsd: string, costUsdt: string | null): string | null {
  if (costUsdt === null) return null;
  const raw = marginFromCostAndPrice(costUsdt, priceUsd);
  if (raw === "") return null;
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value.toFixed(1) : null;
}

/** Rounds to the same 6-decimal precision `cost_usdt` is stored at, so two
 *  costs that only differ beyond that precision (float noise from
 *  `Number.parseFloat`) don't get treated as a tie-break by accident. */
function round6(value: number): number {
  return Math.round(value * 1e6) / 1e6;
}

/** Every supplier tied for cheapest on this row, among suppliers that are
 *  both actively mapped and have a recorded cost — display-only comparison,
 *  same precedent as `marginPercent` above.
 *
 *  Plural and a `Set` on purpose: two suppliers priced identically are
 *  honestly a tie, and a strict "first one wins" comparison used to mark
 *  only one of them as "дешевле всех" while showing the other at the exact
 *  same displayed cost — a silent, arbitrary preference. Every member of the
 *  returned set is equally entitled to the badge. */
export function cheapestSlugs(suppliers: readonly SourcingBrandSupplierOut[]): ReadonlySet<string> {
  const candidates: { slug: string; value: number }[] = [];
  for (const s of suppliers) {
    if (!s.has_active_mapping || s.latest_cost_usdt === null) continue;
    const value = Number.parseFloat(s.latest_cost_usdt);
    if (!Number.isFinite(value)) continue;
    candidates.push({ slug: s.supplier_slug, value: round6(value) });
  }
  if (candidates.length === 0) return new Set();
  const min = Math.min(...candidates.map((c) => c.value));
  return new Set(candidates.filter((c) => c.value === min).map((c) => c.slug));
}
