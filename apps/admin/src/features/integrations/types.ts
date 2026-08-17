/** Shared types for the integrations admin pages. */

/** Ceiling on how long a connectivity/balance probe is allowed to hang
 *  before we treat it as failed. Supplier health endpoints call out to a
 *  third party with no server-side timeout of their own — without a client
 *  timeout a dead upstream leaves the "Проверяем…" badge spinning forever
 *  and the gated Sync/Pricing actions permanently disabled. */
export const HEALTH_CHECK_TIMEOUT_MS = 8_000;

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
  /** Human-readable code (e.g. "steam-50-usd") — always prefer this over `sku_id`
   *  in the UI; an operator can't tell which SKU a raw UUID belongs to. */
  sku_code: string;
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

export interface PricePoint {
  id: string;
  sku_id: string;
  supplier_slug: string;
  kind: string;
  external_product_id: string;
  external_variant_id: string | null;
  cost_usdt: string;
  previous_cost_usdt: string | null;
  source: string | null;
  captured_at: string;
}

export interface PriceHistoryListOut {
  items: PricePoint[];
}

export interface PriceRefreshOut {
  checked: number;
  moved: number;
  alerts_sent: number;
  errors: number;
}

/** All G2B-flavoured slugs we expose in the admin today. Extend when adding
 *  Steam / Riot / etc. */
export const KNOWN_SUPPLIERS = ["g2b", "waxpeer", "gengine"] as const;
export type KnownSupplier = (typeof KNOWN_SUPPLIERS)[number];

export const SUPPLIER_LABELS: Record<KnownSupplier, string> = {
  g2b: "G2Bulk",
  waxpeer: "Waxpeer",
  gengine: "G-Engine",
};

/**
 * What a supplier actually supports, so the page offers only what will work.
 *
 * Waxpeer sells one thing — a Steam wallet top-up priced by the dollar amount
 * the customer types — so there is no product list to browse, cache or map a
 * SKU onto, and no per-mapping cost to refresh. It has zero rows in
 * `sku_supplier_mapping` and `supplier_catalog_cache` for that reason, not
 * because someone forgot. Showing those actions anyway would offer buttons
 * that can only fail.
 */
export interface SupplierCapabilities {
  /** Has a browsable/syncable product catalogue and SKU mappings built on it. */
  catalogue: boolean;
}

export const SUPPLIER_CAPABILITIES: Record<KnownSupplier, SupplierCapabilities> = {
  g2b: { catalogue: true },
  waxpeer: { catalogue: false },
  // Its catalogue lives behind `/recharge/services`, which the import
  // wizard does not speak yet — the mapping is hand-entered for now.
  gengine: { catalogue: false },
};

/** Why a supplier shows no catalogue tooling — stated rather than left as a
 *  suspicious absence. */
export const SUPPLIER_NO_CATALOGUE_NOTE: Partial<Record<KnownSupplier, string>> = {
  gengine:
    "Каталог G-Engine (сервисы пополнения) пока не импортируется мастером — " +
    "маппинг SKU заводится вручную: service_id в external_product_id, " +
    "denomination_id в external_variant_id.",
  waxpeer:
    "Waxpeer пополняет Steam-кошелёк на введённую сумму — у него нет списка товаров, " +
    "поэтому каталог, маппинг SKU и обновление цен здесь неприменимы.",
};

export interface GameImportDenom {
  catalogue_name: string;
  denomination: string;
  sku_code: string;
  cost_usdt: string;
  price_usd_override?: string;
  region?: string;
  quantity: number;
}

export interface GameImportPayload {
  game_code: string;
  target: "new_brand" | "existing_brand";
  brand_id?: string;
  new_brand?: {
    slug: string;
    category_id: string;
    name: string;
    logo_url?: string;
    hero_image_url?: string;
    accent_color?: string;
  };
  product: {
    slug: string;
    name: string;
    required_fields: FormFieldDto[];
    image_url?: string;
  };
  margin_percent: string;
  denominations: GameImportDenom[];
}

export interface GameImportResult {
  brand_id: string;
  product_id: string;
  created_skus: number;
  created_mappings: number;
  skipped: string[];
}

/** Minimal FormField shape we send to the API (matches catalog FormField). */
export interface FormFieldDto {
  key: string;
  label: { ru: string; en: string; uz: string };
  type: "text";
  required: boolean;
}

/** Best-effort ru/en/uz labels for common G2B field names; fallback to the raw key. */
export function g2bFieldLabel(key: string): { ru: string; en: string; uz: string } {
  const map: Record<string, { ru: string; en: string; uz: string }> = {
    userid: { ru: "ID игрока", en: "Player ID", uz: "Oʻyinchi ID" },
    zoneid: { ru: "ID сервера", en: "Server ID", uz: "Server ID" },
    server: { ru: "Сервер", en: "Server", uz: "Server" },
    charname: { ru: "Имя персонажа", en: "Character name", uz: "Belgi nomi" },
  };
  return map[key.toLowerCase()] ?? { ru: key, en: key, uz: key };
}
