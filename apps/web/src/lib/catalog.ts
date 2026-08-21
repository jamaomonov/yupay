/**
 * Catalog data access — now backed by the live API (`/catalog/*`). The DTOs
 * mirror yupay.modules.catalog.schemas; the API localises name/description by
 * Accept-Language and returns FX-converted `display_price` when a currency is
 * passed. Server Components call these directly.
 */
import { apiGet, apiGetOrNull } from "./api";

export interface PriceOut {
  amount: string;
  currency: string;
  source: "usd" | "override" | "fx";
}

export type LocaleMap = Record<string, string>;

export interface FormOption {
  value: string;
  label: LocaleMap;
}

export interface FieldCheck {
  provider: "g2b";
  server_field?: string | null;
}

export interface FormField {
  key: string;
  label: LocaleMap;
  type: "text" | "email" | "number" | "select";
  required: boolean;
  placeholder?: LocaleMap | null;
  help_text?: LocaleMap | null;
  pattern?: string | null;
  options?: FormOption[] | null;
  check?: FieldCheck | null;
}

export interface BrandRating {
  avg: number;
  count: number;
}

export interface BrandSummary {
  id: string;
  slug: string;
  category_slug: string;
  name: string;
  short_description: string | null;
  logo_url: string | null;
  hero_image_url: string | null;
  accent_color: string | null;
  maintenance: boolean;
  // Optional: an older deployed API (or a build prerendering against one) may
  // omit this, so consumers must tolerate `undefined` and treat it as "no reviews".
  rating?: BrandRating | null;
}

export interface CategoryOut {
  id: string;
  slug: string;
  icon: string | null;
  name: string;
  description: string | null;
}

export interface SkuOut {
  id: string;
  sku_code: string;
  denomination: string | null;
  region: string | null;
  image_url: string | null;
  price_usd: string;
  // Optional: an older deployed API (or a build prerendering against one, see
  // web-ssg-prerenders-against-deployed-api) may not send these yet.
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
  // optional for the same build-time-prerender reason as `units` above.
  min_qty?: number | null;
  max_qty?: number | null;
  // Gift cards are finite: the supplier holds real codes and runs out. Optional
  // and defaulted to sellable at every use site, because a build prerendering
  // against the older deployed API would otherwise grey out the whole catalog.
  in_stock?: boolean;
  display_price: PriceOut | null;
}

export interface ProductSummary {
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

export interface Faq {
  id: string;
  question: string;
  answer: string;
}

export interface BrandDetail extends BrandSummary {
  description: string | null;
  // Optional: an older deployed API (or a build prerendering against one) may
  // omit these, so consumers must tolerate `undefined` — not just `null`.
  instructions?: string | null;
  products?: ProductSummary[];
  faqs?: Faq[];
  // Optional: an older deployed API (or a build prerendering against one) may
  // omit this, so consumers must tolerate `undefined` and default to `[]`.
  highlights?: string[];
}

export interface ProductDetail extends ProductSummary {
  brand: BrandSummary;
  description: string | null;
  required_fields: FormField[];
  skus: SkuOut[];
}

const REVALIDATE = 300;

export async function getCategories(locale: string): Promise<CategoryOut[]> {
  const r = await apiGet<{ items: CategoryOut[] }>("/catalog/categories", {
    locale,
    revalidate: REVALIDATE,
  });
  return r.items;
}

export async function getBrands(locale: string, category?: string): Promise<BrandSummary[]> {
  const q = category && category !== "all" ? `?category=${encodeURIComponent(category)}` : "";
  const r = await apiGet<{ items: BrandSummary[] }>(`/catalog/brands${q}`, {
    locale,
    revalidate: REVALIDATE,
  });
  return r.items;
}

export function getBrandDetail(
  slug: string,
  locale: string,
  currency?: string,
): Promise<BrandDetail | null> {
  return apiGetOrNull<BrandDetail>(`/catalog/brands/${encodeURIComponent(slug)}`, {
    locale,
    revalidate: REVALIDATE,
    ...(currency ? { currency } : {}),
  });
}

export function getProductDetail(
  slug: string,
  locale: string,
  currency?: string,
): Promise<ProductDetail | null> {
  return apiGetOrNull<ProductDetail>(`/catalog/products/${encodeURIComponent(slug)}`, {
    locale,
    revalidate: REVALIDATE,
    ...(currency ? { currency } : {}),
  });
}

/** Brand slugs for sitemap + static params. Resilient: returns [] if the API
 * is unreachable (e.g. at build time) so the build never fails on it. */
export async function getBrandSlugs(): Promise<string[]> {
  try {
    const items = await getBrands("ru");
    return items.map((b) => b.slug);
  } catch {
    return [];
  }
}
