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

export type CatalogKind = "voucher" | "game" | "game_denom" | "voucher_denom";

export interface CatalogEntry {
  supplier_slug: string;
  kind: CatalogKind;
  external_id: string;
  title: string;
  raw: Record<string, unknown>;
  fetched_at: string;
  /** For a `game_denom` row, the `external_id` of the game it belongs to;
   *  for a `voucher_denom` row, the voucher product's. Null for
   *  `game`/`voucher` rows, which have no parent.
   *
   *  A voucher is flat only where the supplier sells it flat: G2B's codes
   *  are one product at one price, while NOVA's gift-card categories and
   *  G-Engine's shop products each hold a ladder. */
  parent_external_id: string | null;
  /** The supplier's own price for this entry, when they report one —
   *  a string straight through from the API (§9: money never becomes a
   *  float client-side). Parse only for display; never do arithmetic on it
   *  here. */
  price_usdt: string | null;
}

export interface CatalogListOut {
  items: CatalogEntry[];
}

/** Builds a minimal `CatalogEntry` for an id the UI knows about but the
 *  cache doesn't — a value typed by hand, or one prefilled from an
 *  existing mapping row that predates (or outran) the cache. Centralised so
 *  every call site fills the same fields the same way; a field added to
 *  `CatalogEntry` only needs updating here. */
export function syntheticCatalogEntry(
  supplierSlug: string,
  kind: CatalogKind,
  externalId: string,
  parentExternalId: string | null = null,
): CatalogEntry {
  return {
    supplier_slug: supplierSlug,
    kind,
    external_id: externalId,
    title: externalId,
    raw: {},
    fetched_at: new Date().toISOString(),
    parent_external_id: parentExternalId,
    price_usdt: null,
  };
}

export interface CatalogSyncResult {
  supplier: string;
  vouchers_synced: number;
  games_synced: number;
  /** Mappings re-priced from the cache this sync just wrote, and how many
   *  moved. The sync used to stop at `supplier_catalog_cache`, which nothing
   *  an operator looks at reads — the sourcing comparison reads
   *  `supplier_price_history` — so a sync appeared to do nothing until the
   *  hourly re-price caught up. */
  prices_checked: number;
  prices_moved: number;
  error: string | null;
}

/** Response of `POST /admin/integrations/{supplier}/games/{game_id}/sync-denominations`
 *  (`DenomSyncOut` on the backend). Only `nova` and `gengine` accept this
 *  route — G2B's denominations were never moved into `supplier_catalog_cache`
 *  and keep their own live picker (`DenomPicker` in `gameWidgets.tsx`). */
export interface SyncDenominationsResult {
  supplier: string;
  game_id: string;
  denominations_synced: number;
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
export const KNOWN_SUPPLIERS = ["g2b", "waxpeer", "gengine", "nova"] as const;
export type KnownSupplier = (typeof KNOWN_SUPPLIERS)[number];

export const SUPPLIER_LABELS: Record<KnownSupplier, string> = {
  g2b: "G2Bulk",
  waxpeer: "Waxpeer",
  gengine: "G-Engine",
  nova: "NOVA",
};

/**
 * Suppliers a SKU is never routed to **automatically** — mirrors
 * `RESERVE_SUPPLIERS` in `apps/api/src/yupay/modules/integrations/models.py`
 * (ADR-0081). A reserve is reached only through an explicit `force_supplier`
 * choice, never as the outcome of `mode: "auto"`; no sourcing screen may
 * offer one as an automatic route.
 *
 * This is a straight port of the backend set (ADR-0082's lesson: a rule
 * that exists on both sides of the API has two homes — change one, change
 * both). Used by the sourcing screens to label a reserve supplier's cost
 * cell ("резерв") and to keep it out of anything that would imply "auto"
 * — it stays fully offerable as an explicit `force_supplier` target.
 */
export const RESERVE_SUPPLIERS: ReadonlySet<string> = new Set(["nova"]);

/**
 * What a supplier actually supports, so the page offers only what will work.
 *
 * Two different questions used to share one `catalogue` flag, which meant a
 * supplier with a sync endpoint but no importer (or vice versa) had no way to
 * say so:
 *
 * - `catalogueSync` — has a browsable/syncable product catalogue
 *   (`POST /{supplier}/sync-catalog`) that the mapping wizard's pickers read
 *   from `supplier_catalog_cache`. Mirrors the backend's
 *   `SYNCABLE_SUPPLIERS` (`catalog_sync.py`).
 * - `gameImport` — can turn a browsed catalogue game into a Brand + Product +
 *   SKUs in one action (`SupplierCatalogPage`'s per-row "Импортировать" →
 *   `GameImportPage`). G2B-only: the importer posts to the G2B-specific
 *   `POST /g2b/import` regardless of which supplier's catalogue page linked
 *   to it, so offering the link for another supplier would 404.
 *
 * Waxpeer sells one thing — a Steam wallet top-up priced by the dollar amount
 * the customer types — so there is no product list to browse, cache or map a
 * SKU onto, and no per-mapping cost to refresh. It has zero rows in
 * `sku_supplier_mapping` and `supplier_catalog_cache` for that reason, not
 * because someone forgot. Showing those actions anyway would offer buttons
 * that can only fail.
 */
export interface SupplierCapabilities {
  catalogueSync: boolean;
  gameImport: boolean;
}

export const SUPPLIER_CAPABILITIES: Record<KnownSupplier, SupplierCapabilities> = {
  g2b: { catalogueSync: true, gameImport: true },
  waxpeer: { catalogueSync: false, gameImport: false },
  // G-Engine's catalogue now syncs (`POST /gengine/sync-catalog`) into the
  // same cache the mapping wizard's pickers read — but there is no importer
  // for it, so `gameImport` stays false.
  gengine: { catalogueSync: true, gameImport: false },
  // Same story as G-Engine: NOVA's catalogue syncs now, but only G2B has an
  // importer.
  nova: { catalogueSync: true, gameImport: false },
};

/**
 * Looks up a slug's capabilities the way every caller reading a slug from the
 * URL should. Known suppliers get the truth from `SUPPLIER_CAPABILITIES`
 * above; an unknown one — a supplier someone just added and hasn't listed
 * here yet — gets the two defaults decided by what a wrong guess costs.
 *
 * `catalogueSync` defaults **true**: the route it drives is typed
 * `Literal[...]` on the backend, so an unsupported slug comes back as a clean
 * 422 the operator can read. Offering a button that might answer "not
 * supported" beats hiding tooling that does work.
 *
 * `gameImport` defaults **false**, and the asymmetry is the point. That link
 * posts to `/g2b/import`, hardcoded — for any other supplier it would not
 * fail, it would *succeed at the wrong thing*, importing a G2B game while the
 * operator is looking at someone else's catalogue. A silent wrong action is
 * worse than a missing button, so an unknown supplier does not get offered
 * one.
 */
export function capabilitiesFor(slug: string): SupplierCapabilities {
  return isKnownSupplier(slug)
    ? SUPPLIER_CAPABILITIES[slug]
    : { catalogueSync: true, gameImport: false };
}

/**
 * Every route a fulfilment task can carry, in one place.
 *
 * Four screens used to keep their own list and all four had drifted: the
 * mapping form was hardcoded to G2B, the sourcing rules offered only G2B, and
 * the inbox filter listed five stub suppliers that have never produced a task
 * while omitting the two that produce all of them. A supplier added in one
 * place but not the others is invisible in exactly the screens needed to wire
 * it up.
 */
export interface FulfilmentRoute {
  slug: string;
  label: string;
  /** Whether a SKU has to be wired to this supplier through a mapping row
   *  before it can be fulfilled. Waxpeer derives its Steam top-up from the
   *  order itself and needs none, so offering it in the mapping form would be
   *  an option that silently does nothing. */
  mappings: boolean;
  /** False for the in-house routes (warehouse, manual, dev mock) — they have
   *  no API key, no health probe and no place on the integrations page. */
  external: boolean;
  note: string;
}

export const FULFILMENT_ROUTES: FulfilmentRoute[] = [
  {
    slug: "inventory",
    label: "Склад кодов",
    external: false,
    mappings: false,
    note: "наш склад ваучеров",
  },
  {
    slug: "manual",
    label: "Ручная выдача",
    external: false,
    mappings: false,
    note: "оператор выдаёт руками",
  },
  { slug: "g2b", label: "G2Bulk", external: true, mappings: true, note: "игры и ваучеры" },
  { slug: "waxpeer", label: "Waxpeer", external: true, mappings: false, note: "пополнение Steam" },
  {
    slug: "gengine",
    label: "G-Engine",
    external: true,
    mappings: true,
    note: "игры + подарочные карты",
  },
  {
    slug: "nova",
    label: "NOVA",
    external: true,
    mappings: true,
    note: "резерв: пополнения игр",
  },
  {
    slug: "mock",
    label: "Mock (dev)",
    external: false,
    mappings: false,
    note: "только для разработки",
  },
];

/** NOVA's Steam wallet mapping: no category upstream, so no denomination. */
export const NOVA_STEAM_SENTINEL = "steam-topup";

/** Whether this mapping buys an **amount** rather than a catalogue entry, so
 *  the denomination is optional and step 5's quantity says how much to buy.
 *
 *  Two shapes qualify, and the second is one row rather than a supplier:
 *  G-Engine's `unfixed` services (Telegram Stars is one), and NOVA's Steam
 *  mapping specifically. A NOVA *game* mapping still needs its offer id.
 *
 *  **This mirrors `_is_amount_priced` in `integrations/service.py`, and the
 *  mirror is the point.** The backend is what actually accepts a null variant;
 *  this gate only decides whether the wizard lets you try. When the two
 *  disagree the Save button stays disabled on a mapping the API would have
 *  accepted — which is how NOVA's Steam reserve was briefly unreachable from
 *  the admin while its API call worked fine. Change one, change both. */
export function isAmountPriced(slug: string, externalProductId = ""): boolean {
  if (slug === "gengine") return true;
  return slug === "nova" && externalProductId.trim() === NOVA_STEAM_SENTINEL;
}

function isKnownSupplier(slug: string): slug is KnownSupplier {
  return (KNOWN_SUPPLIERS as readonly string[]).includes(slug);
}

/** Best-effort human label for a supplier slug — same narrowing precedent
 *  as `capabilitiesFor` above. Used by the SKU price-history card/modal
 *  to say which supplier a row's price belongs to, now that
 *  `supplier_price_history` can interleave rows from more than one active
 *  mapping for the same SKU. */
export function supplierLabel(slug: string): string {
  return isKnownSupplier(slug) ? SUPPLIER_LABELS[slug] : slug;
}

/** Why a supplier shows no catalogue tooling — stated rather than left as a
 *  suspicious absence. Only Waxpeer belongs here now: G-Engine and NOVA both
 *  gained a sync endpoint on this branch and no longer need a by-hand note
 *  (`capabilitiesFor(slug).catalogueSync` is true for both). */
export const SUPPLIER_NO_CATALOGUE_NOTE: Partial<Record<KnownSupplier, string>> = {
  waxpeer:
    "Waxpeer пополняет Steam-кошелёк на введённую сумму — у него нет списка товаров, " +
    "поэтому каталог, маппинг SKU и обновление цен здесь неприменимы.",
};

/**
 * Suppliers whose game denominations are cached in `supplier_catalog_cache`
 * and syncable on demand via `POST /{supplier}/games/{game_id}/sync-denominations`
 * — mirrors `DENOM_SYNCABLE_SUPPLIERS` in
 * `apps/api/src/yupay/modules/integrations/catalog_sync.py`. G2B is
 * deliberately excluded: its denominations were never moved into the cache,
 * and it keeps its own live `DenomPicker` (`gameWidgets.tsx`) instead of the
 * cache-backed `DenomCatalogPicker`.
 *
 * This is a straight port of the backend set (ADR-0082's lesson: a rule that
 * exists on both sides of the API has two homes — change one, change both).
 * `MappingEditPage` branches on membership here — a positive allowlist,
 * mirroring the backend's own — rather than a `supplier === "g2b"`
 * exclusion, so a future mappable supplier that isn't denomination-syncable
 * doesn't silently get a picker with a pull button that 422s.
 */
export const DENOM_CACHE_SUPPLIERS: ReadonlySet<string> = new Set(["nova", "gengine"]);

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
