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
