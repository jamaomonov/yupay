import type { CostSyncResult } from "../integrations/types";

export type SourcingMode = "auto" | "force_inventory" | "force_supplier" | "manual";

export interface SourcingRuleOut {
  sku_id: string;
  /** Human-readable code — always prefer this over `sku_id` in the UI. */
  sku_code: string;
  mode: SourcingMode;
  supplier_slug: string | null;
  updated_by: string | null;
  updated_at: string;
  /** What the switch did to our cost basis. A route change changes who we
   *  buy from, so the cost becomes the new supplier's price in the same
   *  request. `null` on a listing, which re-priced nothing. */
  cost_sync: CostSyncResult | null;
}

export interface SourcingRuleListOut {
  items: SourcingRuleOut[];
}

export interface SourcingDecisionOut {
  primary: string;
  fallback: string | null;
  strict: boolean;
  rule_present: boolean;
}

/** One candidate supplier's mapping + latest recorded cost for a single SKU
 *  (mirrors `SourcingBrandSupplierOut` in `sourcing/schemas.py`).
 *
 *  `latest_cost_usdt` is a string, not a number — money fields arrive from
 *  the API as JSON strings and stay strings all the way to display
 *  (AGENTS.md §9); only `Number.parseFloat` it for a *display* comparison
 *  (picking the cheapest), same as `SkuPriceHistoryCard`/`SkuPriceHistoryModal`
 *  already do with `cost_usdt`, never to build a request body. */
export interface SourcingBrandSupplierOut {
  supplier_slug: string;
  has_active_mapping: boolean;
  latest_cost_usdt: string | null;
  captured_at: string | null;
  /** Where `latest_cost_usdt` came from (mirrors the backend's
   *  `cost_source` field, `sourcing/schemas.py`'s `SourcingBrandSupplierOut`).
   *  `supplier_price_history` records a price *change* — a supplier whose
   *  cost never moved has zero history rows even though its current price
   *  is exactly `Sku.cost_usdt` (every Free Fire SKU on g2b is this case).
   *
   *  - `"history"` — a captured `supplier_price_history` row; render as a
   *    captured price with its `captured_at` date, same as before this
   *    field existed.
   *  - `"current"` — no history row, but this supplier is the one the SKU
   *    routes to, so `latest_cost_usdt` is `Sku.cost_usdt` and
   *    `captured_at` is `null` — mark it as the SKU's current cost, not a
   *    captured price, so an operator can tell the two apart at a glance.
   *  - `null` — genuinely unknown; keep rendering "цена не снята".
   *
   *  A `"current"` cost participates in the cheapest-supplier comparison
   *  exactly like a captured one — `cheapestSlugs` (`brandSourcingFormat.ts`)
   *  only looks at `has_active_mapping`/`latest_cost_usdt`, never this field. */
  cost_source: "history" | "current" | null;
}

/** One active SKU's sourcing picture for the brand-overview screen
 *  (mirrors `SourcingBrandSkuOut`). `primary` is `"inventory"`,
 *  `"supplier:<slug>"` (including the non-supplier `"supplier:manual"`
 *  sentinel), or `"invalid"` for a malformed rule the screen still needs to
 *  show rather than crash on.
 *
 *  `fallback` mirrors `Decision.fallback` (same shape as `primary`, or
 *  `null` when the route is `strict`). For a voucher SKU on the automatic
 *  route, `primary` is `"inventory"` and the cost owner — the supplier the
 *  warehouse falls back to, and whose cost the operator is actually
 *  comparing — lives in `fallback`, not `primary`. A screen that only ever
 *  reads `primary` to decide "which supplier is current" marks no
 *  supplier at all for that row (whole-branch review, Important #2). */
export interface SourcingBrandSkuOut {
  sku_id: string;
  sku_code: string;
  denomination: string | null;
  product_slug: string;
  /** `"top_up"` | `"voucher"` (mirrors `Product.kind`'s DB check
   *  constraint) — a bare `string` here, same as `SkuPickerRow.
   *  product_kind`, not a narrower union: the backend field
   *  (`sourcing/schemas.py`'s `SourcingBrandSkuOut.product_kind`) is typed
   *  `str`, not a `Literal`.
   *
   *  Exists so this screen can stop *offering* an action the backend
   *  already refuses: `sourcing.service.set_rule` rejects
   *  `mode="force_inventory"` on a `top_up` SKU (the code warehouse holds
   *  voucher codes; a top-up SKU has nothing there to issue) — and
   *  `primary`/`fallback` cannot substitute for a kind signal, since a
   *  `top_up` SKU under `mode="auto"` never reports `primary ==
   *  "inventory"` in the first place (`_auto_decision` only ever gives it
   *  `supplier:<slug>` or `supplier:manual`). See
   *  `brandSourcingFormat.forceInventoryDisabledReason`. */
  product_kind: string;
  price_usd: string;
  cost_usdt: string | null;
  primary: string;
  fallback: string | null;
  rule_present: boolean;
  suppliers: SourcingBrandSupplierOut[];
}

export interface SourcingBrandOverviewOut {
  items: SourcingBrandSkuOut[];
}

/** Per-request cap on `SourcingBulkRuleIn.sku_ids` — mirrors
 *  `MAX_BULK_SKU_IDS`, defined in `apps/api/src/yupay/modules/sourcing/schemas.py`
 *  and enforced in `apps/api/src/yupay/modules/sourcing/bulk_rules.py`
 *  (a request over this cap 422s). A brand can have more active SKUs than
 *  this, so a "select all, switch" action must chunk the selection into
 *  requests of at most this many ids — see `bulkSwitch.ts`. */
export const MAX_BULK_SKU_IDS = 100;

export interface SourcingBulkRuleIn {
  sku_ids: string[];
  mode: SourcingMode;
  supplier_slug: string | null;
}

/** One SKU's outcome inside a bulk write — success or a named failure. */
export interface SourcingBulkRuleResultOut {
  sku_id: string;
  ok: boolean;
  error: string | null;
}

export interface SourcingBulkRuleOut {
  items: SourcingBulkRuleResultOut[];
}
