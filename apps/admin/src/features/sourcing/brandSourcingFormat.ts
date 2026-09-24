/** Pure display helpers for the brand-overview screen — split out of
 *  `BrandSourcingTable.tsx` to keep that file under the 300-LOC soft limit.
 *  Nothing here does I/O or touches component state. */

import type { SourcingBrandSkuOut, SourcingBrandSupplierOut, SourcingMode } from "./types";

import { SUPPLIER_LABELS, type KnownSupplier } from "@/features/integrations/types";
import { marginFromCostAndPrice } from "@/lib/margin";

/** Shared wording for "this row cannot go to the code warehouse" —
 *  `BrandSourcingTable`'s per-row "склад" control and `BrandSourcingPage`'s
 *  bulk force_inventory switch both need the exact same string: the table
 *  shows it in place of the control it withholds, the page synthesizes a
 *  per-SKU failure entry carrying it for a top-up row inside a mixed bulk
 *  selection (see `partitionForceInventorySelection`). One constant so the
 *  two treatments of the same fact can never drift apart. */
export const FORCE_INVENTORY_TOPUP_ERROR = "топ-ап — со склада коды не выдаются";

/** Why `force_inventory` must not be offered for this row — `null` when it
 *  is offerable. Mirrors the single-SKU editor's `SourcingModeCards.
 *  disabledReasonFor` and the backend guard `sourcing.service.set_rule` now
 *  enforces (a `top_up` SKU rejected with a 4xx): the code warehouse holds
 *  voucher codes, and a top-up SKU has nothing there a payment could ever
 *  be fulfilled from. */
export function forceInventoryDisabledReason(productKind: string): string | null {
  return productKind === "top_up" ? FORCE_INVENTORY_TOPUP_ERROR : null;
}

/** Splits a ticked selection into the SKUs a bulk `force_inventory` switch
 *  can actually apply to and the ones it cannot (`top_up` rows) — the case
 *  to get right is a mixed selection: neither silently dropping the
 *  top-ups (they'd look switched when they were never sent) nor blocking
 *  the whole action (the voucher rows in the same selection are legitimate
 *  and would otherwise wait on an unrelated row). The caller sends
 *  `applicable` over the wire and reports `blocked` the same way a real
 *  per-SKU rejection is reported — see `BrandSourcingPage`'s
 *  `switchMutation`.
 *
 *  Iterates the *selection*, not `items` — a ticked id can outlive the
 *  overview row it came from (deactivated between load and apply; the
 *  selection survives a refetch), and iterating `items` instead used to
 *  leave such an id neither applicable nor blocked: never sent, never
 *  reported, permanently ticked (whole-branch review #4). An id with no
 *  matching row is treated as applicable so the server gets a chance to
 *  answer for it, the same per-item "not found" every other mode already
 *  relies on. */
export function partitionForceInventorySelection(
  items: readonly Pick<SourcingBrandSkuOut, "sku_id" | "product_kind">[],
  selected: ReadonlySet<string>,
): { applicable: string[]; blocked: string[] } {
  const itemBySku = new Map(items.map((item) => [item.sku_id, item]));
  const applicable: string[] = [];
  const blocked: string[] = [];
  for (const skuId of selected) {
    const item = itemBySku.get(skuId);
    if (item?.product_kind === "top_up") blocked.push(skuId);
    else applicable.push(skuId);
  }
  return { applicable, blocked };
}

/** Whether `slug` is this row's current cost owner — either the primary
 *  route (`primary === "supplier:<slug>"`) or, for a voucher SKU on the
 *  automatic route, the supplier the code warehouse falls back to
 *  (`primary === "inventory" && fallback === "supplier:<slug>"`).
 *
 *  A voucher SKU's automatic route is `primary="inventory"`,
 *  `fallback="supplier:<slug>"` — the warehouse first, that supplier as
 *  backup. Reading only `primary` to decide "which supplier is current"
 *  marks no supplier at all on that row (whole-branch review, Important
 *  #2), even though `fallback` names exactly who the operator is
 *  comparing costs against. */
export function isCurrentSupplierRoute(
  item: Pick<SourcingBrandSkuOut, "primary" | "fallback">,
  slug: string,
): boolean {
  if (item.primary === `supplier:${slug}`) return true;
  return item.primary === "inventory" && item.fallback === `supplier:${slug}`;
}

/** Whether switching this row to an explicit supplier — via the row's own
 *  per-column control — takes the code warehouse out of routing entirely.
 *
 *  `force_supplier` answers `primary="supplier:<slug>"`,
 *  `fallback=None`, `strict=true`: no fallback, so the warehouse is never
 *  tried again for this SKU once switched (whole-branch review, Important
 *  #1). That is only a change in behaviour for a SKU whose *current*
 *  route already goes through the warehouse first — `primary ===
 *  "inventory"` — which today is every voucher SKU on the automatic
 *  route. A row already routed straight to a supplier has nothing to lose
 *  by switching to another one. */
export function bypassesInventory(item: Pick<SourcingBrandSkuOut, "primary">): boolean {
  return item.primary === "inventory";
}

/** Best-effort human label for a supplier slug — a `switch` over the known
 *  set rather than indexing `SUPPLIER_LABELS` with a bare `string` (which
 *  `Record<KnownSupplier, string>` correctly refuses without narrowing
 *  first, and this project's rules bar an `as` cast for anything short of
 *  a known-shape JSON/DOM narrowing). */
export function supplierLabel(slug: string): string {
  const known: readonly KnownSupplier[] = ["g2b", "waxpeer", "gengine", "nova", "fzr"];
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

// Human name for each bulk mode, used only in the confirmation prompt below
// — the <option> labels in `BrandSourcingToolbar` stay inline since they're
// rendered once each and never reused elsewhere.
const BULK_MODE_CONFIRM_LABELS: Record<SourcingMode, string> = {
  force_supplier: "поставщика",
  force_inventory: "режим «Только склад»",
  manual: "режим «Вручную»",
  auto: "режим «Авто»",
};

/** How many of the given SKUs currently route through the code warehouse
 *  first (`primary === "inventory"`) — the population a `force_supplier`
 *  bulk switch would cut off from the warehouse entirely (Important #1). */
export function inventoryRoutedCount(
  items: readonly Pick<SourcingBrandSkuOut, "sku_id" | "primary">[],
  selected: ReadonlySet<string>,
): number {
  let count = 0;
  for (const item of items) {
    if (selected.has(item.sku_id) && item.primary === "inventory") count += 1;
  }
  return count;
}

/** Confirmation text for the bulk-apply button. Always names the count and
 *  the target (pre-existing behaviour); when the bulk mode is
 *  `force_supplier` and any selected row is currently routed through the
 *  code warehouse, appends the consequence explicitly — `force_supplier`
 *  sets `fallback=None`, so those rows lose the warehouse fallback
 *  entirely, not just gain a new preferred supplier (whole-branch review,
 *  Important #1). */
export function bulkConfirmMessage(
  selectedCount: number,
  mode: SourcingMode,
  supplierSlug: string,
  bypassCount: number,
): string {
  const target =
    mode === "force_supplier"
      ? `поставщика ${supplierLabel(supplierSlug)}`
      : BULK_MODE_CONFIRM_LABELS[mode];
  let message = `Переключить ${selectedCount.toString()} SKU на ${target}?`;
  if (mode === "force_supplier" && bypassCount > 0) {
    message +=
      `\n\n${bypassCount.toString()} из них сейчас выдаются со склада кодов — склад ` +
      "перестанет использоваться для них совсем, даже если код есть в остатке.";
  }
  return message;
}
