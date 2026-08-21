/**
 * Catalog hooks: adapt the API's Category → Brand → Product → SKU hierarchy to
 * the prototype's flat ``Game / Package`` shape.
 *
 * The mapping is intentionally lossy: each Brand becomes one "Game", and that
 * Game's packages come from the brand's first active product's SKUs. A brand
 * with several products (e.g. PUBG UC vs Royale Pass) currently surfaces only
 * its first product in the miniapp — we'll add a product picker once the API
 * wiring stabilises.
 */

import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./api";

import type { Category, Game } from "./constants-types";

// --- API DTOs (subset of what catalog.schemas returns) --------------------

interface BrandApi {
  id: string;
  slug: string;
  category_slug: string;
  name: string;
  short_description: string | null;
  logo_url: string | null;
  hero_image_url: string | null;
  accent_color: string | null;
  maintenance: boolean;
}

interface CategoryApi {
  id: string;
  slug: string;
  icon: string | null;
  name: string;
  description: string | null;
}

interface PriceOut {
  amount: string; // decimal
  currency: string;
  source: "usd" | "override" | "fx";
}

interface SkuApi {
  id: string;
  sku_code: string;
  denomination: string | null;
  region: string | null;
  image_url: string | null;
  price_usd: string;
  // Optional: an older deployed API may not send these yet — see
  // web-ssg-prerenders-against-deployed-api (the same risk applies to any
  // build/runtime hitting a stale API before this field shipped).
  variable_amount?: boolean;
  // Optional on purpose: `next build` prerenders against the deployed API,
  // which does not serve these until this change ships. A required field here
  // fails the production build.
  // How many units a package delivers, so a typed amount can be priced from
  // it. Optional for the same build-time reason as the two above.
  units?: number | null;
  amount_unit?: string | null;
  units_per_usd?: string | null;
  min_amount_usd?: string | null;
  max_amount_usd?: string | null;
  // Admin-configured quantity bounds for a unit SKU (Telegram Stars): the
  // customer types how many of `amount_unit` to buy — or taps a package tile
  // built from `visibleStarPackages` — and checkout sends `qty` directly, no
  // `amount_usd`. Both absent means this SKU isn't sold by typed quantity —
  // same stale-API caveat as `units` above.
  min_qty?: number | null;
  max_qty?: number | null;
  // Gift cards are finite: the supplier holds real codes and runs out. Same
  // stale-API caveat as above — absent means sellable, never the reverse.
  in_stock?: boolean;
  display_price: PriceOut | null;
}

interface ProductSummaryApi {
  id: string;
  slug: string;
  brand_slug: string;
  category_slug: string;
  name: string;
  short_description: string | null;
  image_url: string | null;
  kind: "top_up" | "voucher";
  starting_price_usd: string;
  starting_display_price: PriceOut | null;
}

interface BrandDetailApi extends BrandApi {
  description: string | null;
  products: ProductSummaryApi[];
}

interface ProductDetailApi extends ProductSummaryApi {
  brand: BrandApi;
  description: string | null;
  required_fields: FormField[];
  skus: SkuApi[];
}

export interface FormOption {
  value: string;
  label: Record<string, string>;
}

export interface FieldCheck {
  provider: "g2b";
  server_field?: string | null;
}

export interface FormField {
  key: string;
  label: Record<string, string>;
  type: "text" | "email" | "number" | "select";
  required: boolean;
  placeholder?: Record<string, string> | null;
  help_text?: Record<string, string> | null;
  pattern?: string | null;
  options?: FormOption[] | null;
  check?: FieldCheck | null;
}

// --- adapters --------------------------------------------------------------

/** Bucket an arbitrary category slug into one of the UI's three chips. */
function bucketCategory(slug: string): Category {
  const s = slug.toLowerCase();
  if (s.includes("game")) return "games";
  if (s.includes("card") || s.includes("gift") || s.includes("voucher")) return "cards";
  return "services";
}

function brandToGame(b: BrandApi, locale = "ru"): Game {
  return {
    id: b.slug,
    name: b.name,
    // `short_description` is the SEO paragraph (250+ chars for the flagship
    // brands, straight from the seeds). It is not a publisher, and the UI slots
    // it where "Tencent Games" belongs — clipped and uppercased. Keep the slot
    // empty rather than filling it with marketing copy; callers already fall
    // back to "YuPay".
    publisher: (b.short_description ?? "").length > 40 ? "" : (b.short_description ?? ""),
    category: bucketCategory(b.category_slug),
    category_slug: b.category_slug,
    // ``appIcon`` is the square brand mark — the icon tiles on Home, recent
    // strip and search results all prefer it first. ``bgUrl`` is the wide
    // hero image used by promo cards and the TopUp hero. Map them straight
    // from the API so a brand's logo doesn't get stretched into the hero
    // slot and vice versa.
    appIcon: b.logo_url ?? undefined,
    logoUrl: b.logo_url ?? undefined,
    bgUrl: b.hero_image_url ?? undefined,
    color: b.accent_color ?? "#3b82f6",
    inputType: "text",
    inputPlaceholder: locale === "ru" ? "Введите ID аккаунта" : "Account ID",
    maintenance: b.maintenance,
  };
}

export interface CategoryListItem {
  id: string;
  slug: string;
  name: string;
  icon: string | null;
}

/** Reusable query options for the categories list. Used by ``useCategoriesList``
 *  and by the BootstrapGate prefetch so the cache shape matches the hook. */
export const categoriesQueryOptions = {
  queryKey: ["catalog", "categories"] as const,
  queryFn: async (): Promise<CategoryListItem[]> => {
    const data = await apiGet<{ items: CategoryApi[] }>("/api/v1/catalog/categories", true);
    return data.items.map((c) => ({
      id: c.id,
      slug: c.slug,
      name: c.name,
      icon: c.icon,
    }));
  },
  staleTime: 5 * 60_000,
};

export function useCategoriesList() {
  return useQuery<CategoryListItem[]>(categoriesQueryOptions);
}

export interface Package {
  id: string; // sku id
  sku_code: string;
  // The full denomination string as the operator entered it (``"60 UC"``,
  // ``"Steam 10 USD"``, ``"1 мес"``). We never parse a number out of it —
  // the storefront shows it as-is so suffixes / units / regions survive.
  label: string;
  region: string | null;
  priceUsd: number;
  displayPrice: { amount: number; currency: string } | null;
  imageUrl: string | null;
  // Variable-amount SKUs (Steam wallet top-up): the customer types a dollar
  // amount instead of picking a fixed denomination. ``priceUsd``/
  // ``displayPrice`` above are meaningless for these (the SKU's
  // ``price_usd`` is a ``1``-dollar placeholder) — use ``ratePerDollar``
  // instead, which is the localised price of ONE dollar.
  variableAmount: boolean;
  // Set when the amount is typed in something other than dollars (stars).
  amountUnit: string | null;
  unitsPerUsd: number | null;
  // How many units a package delivers — what a typed amount is priced from.
  units: number | null;
  minAmountUsd: number | null;
  maxAmountUsd: number | null;
  // Admin-configured quantity bounds for a unit SKU (Telegram Stars): the
  // customer types/taps a whole number of `amountUnit` directly, no dollar
  // conversion — see `TopUp.tsx`'s unit-package panel. Both null means this
  // SKU isn't sold by typed quantity.
  minQty: number | null;
  maxQty: number | null;
  /** Localised price of one dollar for a variable-amount SKU. `null` means
   *  the FX trust gate rejected the live rate — not sellable right now,
   *  never fall back to a price of zero/one. Always `null` for a
   *  fixed-price SKU. */
  ratePerDollar: { amount: number; currency: string } | null;
  /** False only when the supplier has run out. A missing field on an older
   *  API reads as in stock — an absent flag must not empty the shelf. */
  inStock: boolean;
}

function skuToPackage(sku: SkuApi): Package {
  const denomination = sku.denomination ?? sku.sku_code;
  const priceUsd = Number.parseFloat(sku.price_usd) || 0;
  const displayPrice = sku.display_price
    ? {
        amount: Number.parseFloat(sku.display_price.amount) || 0,
        currency: sku.display_price.currency,
      }
    : null;
  const variableAmount = sku.variable_amount ?? false;
  return {
    id: sku.id,
    sku_code: sku.sku_code,
    label: denomination,
    region: sku.region,
    priceUsd,
    displayPrice,
    imageUrl: sku.image_url,
    variableAmount,
    amountUnit: sku.amount_unit ?? null,
    unitsPerUsd: sku.units_per_usd != null ? Number.parseFloat(sku.units_per_usd) : null,
    units: sku.units ?? null,
    minAmountUsd: sku.min_amount_usd != null ? Number.parseFloat(sku.min_amount_usd) : null,
    maxAmountUsd: sku.max_amount_usd != null ? Number.parseFloat(sku.max_amount_usd) : null,
    minQty: sku.min_qty ?? null,
    maxQty: sku.max_qty ?? null,
    ratePerDollar: variableAmount ? displayPrice : null,
    inStock: sku.in_stock !== false,
  };
}

// --- queries --------------------------------------------------------------

/** Reusable query options for the brands list. */
export const brandsQueryOptions = {
  queryKey: ["catalog", "brands"] as const,
  queryFn: async (): Promise<Game[]> => {
    const data = await apiGet<{ items: BrandApi[] }>("/api/v1/catalog/brands", true);
    return data.items.map((b) => brandToGame(b));
  },
  staleTime: 5 * 60_000,
};

export function useGames() {
  return useQuery<Game[]>(brandsQueryOptions);
}

export interface BrandSummary {
  id: string;
  slug: string;
  name: string;
  short_description: string | null;
  description: string | null;
  logo_url: string | null;
  hero_image_url: string | null;
  accent_color: string | null;
  maintenance: boolean;
  category_slug: string;
  products: ProductSummaryApi[];
  // Optional: an older deployed API may omit it — tolerate undefined.
  rating?: { avg: number; count: number } | null;
}

/** Brand metadata + the list of products (no SKUs). Cheap, cached separately
 *  so the product switcher can render before we fetch a product's full SKUs. */
export function useBrandSummary(gameId: string | undefined) {
  return useQuery<BrandSummary>({
    queryKey: ["catalog", "brand-summary", gameId],
    enabled: Boolean(gameId),
    queryFn: async () => {
      const data = await apiGet<BrandDetailApi>(`/api/v1/catalog/brands/${gameId ?? ""}`, true);
      return data;
    },
    staleTime: 5 * 60_000,
  });
}

export interface ProductWithSkus {
  product: ProductDetailApi;
  packages: Package[];
}

/** Full product payload (form schema + SKUs). Used by the package picker. */
export function useProductWithSkus(productSlug: string | undefined, currency = "USD") {
  return useQuery<ProductWithSkus>({
    queryKey: ["catalog", "product", productSlug, currency],
    enabled: Boolean(productSlug),
    queryFn: async () => {
      const params = currency && currency !== "USD" ? `?currency=${currency}` : "";
      const product = await apiGet<ProductDetailApi>(
        `/api/v1/catalog/products/${productSlug ?? ""}${params}`,
        true,
      );
      return {
        product,
        packages: product.skus.map(skuToPackage),
      };
    },
    staleTime: 2 * 60_000,
  });
}

export interface ProductSummary {
  id: string;
  slug: string;
  name: string;
  short_description: string | null;
  image_url: string | null;
  kind: "top_up" | "voucher";
}

export function brandProducts(brand: BrandSummary | undefined): ProductSummary[] {
  if (!brand) return [];
  return brand.products.map((p) => ({
    id: p.id,
    slug: p.slug,
    name: p.name,
    short_description: p.short_description,
    image_url: p.image_url,
    kind: p.kind,
  }));
}
