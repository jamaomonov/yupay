/** Shared types for the integrations admin pages. */

export interface SupplierHealth {
  supplier: string;
  available: boolean;
  reason: string | null;
  balance: string | null;
  currency: string | null;
  username: string | null;
  last_checked_at: string | null;
}

export type MappingKind = "voucher" | "game";

export interface SupplierMapping {
  sku_id: string;
  supplier_slug: string;
  kind: MappingKind;
  external_product_id: string;
  external_variant_id: string | null;
  quantity: number;
  extra: Record<string, unknown>;
  is_active: boolean;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface SupplierMappingListOut {
  items: SupplierMapping[];
}

export type CatalogKind = "voucher" | "game" | "game_denom";

export interface CatalogEntry {
  supplier_slug: string;
  kind: CatalogKind;
  external_id: string;
  title: string;
  raw: Record<string, unknown>;
  fetched_at: string;
}

export interface CatalogListOut {
  items: CatalogEntry[];
}

export interface CatalogSyncResult {
  supplier: string;
  vouchers_synced: number;
  games_synced: number;
  error: string | null;
}

export interface AttemptRow {
  task_id: string;
  supplier: string;
  kind: string;
  status: string;
  payload: Record<string, unknown>;
  error: string | null;
  created_at: string;
}

export interface AttemptListOut {
  items: AttemptRow[];
  total: number;
}

/** Compact SKU row from ``GET /admin/catalog/skus/search``. */
export interface SkuPickerRow {
  id: string;
  product_id: string;
  product_name: string;
  product_slug: string;
  product_kind: string;
  sku_code: string;
  denomination: string | null;
  region: string | null;
  price_usd: string;
  active: boolean;
}

/** One denomination row from ``GET /admin/integrations/g2b/games/{code}/catalogue``. */
export interface GameDenomRow {
  catalogue_name: string;
  name: string;
  amount: string | null;
  price: string | null;
  raw: Record<string, unknown>;
}

export interface GameDenomList {
  items: GameDenomRow[];
}

export interface GameFields {
  fields: string[];
  notes: string | null;
}

export interface CheckPlayerResult {
  valid: boolean;
  name: string | null;
  openid: string | null;
  reason: string | null;
}

export interface CostSyncResult {
  updated: boolean;
  old_cost: string | null;
  new_cost: string | null;
  source: string | null;
  reason: string | null;
}

export interface SupplierMappingUpsertResult {
  mapping: SupplierMapping;
  cost_sync: CostSyncResult;
}

/** All G2B-flavoured slugs we expose in the admin today. Extend when adding
 *  Steam / Riot / etc. */
export const KNOWN_SUPPLIERS = ["g2b"] as const;
export type KnownSupplier = (typeof KNOWN_SUPPLIERS)[number];

export const SUPPLIER_LABELS: Record<KnownSupplier, string> = {
  g2b: "G2Bulk",
};
