export type SourcingMode = "auto" | "force_inventory" | "force_supplier" | "manual";

export interface SourcingRuleOut {
  sku_id: string;
  /** Human-readable code — always prefer this over `sku_id` in the UI. */
  sku_code: string;
  mode: SourcingMode;
  supplier_slug: string | null;
  updated_by: string | null;
  updated_at: string;
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
}

/** One active SKU's sourcing picture for the brand-overview screen
 *  (mirrors `SourcingBrandSkuOut`). `primary` is `"inventory"`,
 *  `"supplier:<slug>"` (including the non-supplier `"supplier:manual"`
 *  sentinel), or `"invalid"` for a malformed rule the screen still needs to
 *  show rather than crash on. */
export interface SourcingBrandSkuOut {
  sku_id: string;
  sku_code: string;
  denomination: string | null;
  product_slug: string;
  price_usd: string;
  cost_usdt: string | null;
  primary: string;
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
