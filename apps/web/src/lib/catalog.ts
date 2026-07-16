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
