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

/** That a field is checkable. The API does not say who checks it (the server
 *  picks); an older API still sends `provider`, which nothing reads. */
export interface FieldCheck {
  server_field?: string | null;
}

/** One step image for a field's "где найти" help — a profile screenshot with
 *  the id circled, say. Ordered: the sequence is the walkthrough. `url`
 *  always points at our own media bucket (the backend rejects anything
 *  else), so it can be rendered without sanitising the host. `caption` may
 *  be `null` (not every image carries one) and the list may be empty or
 *  absent — never assume otherwise. Capped at 6 server-side; that cap is the
 *  backend's business, not this type's. */
export interface HelpImage {
  url: string;
  caption: LocaleMap | null;
}

export interface FormField {
  key: string;
  label: LocaleMap;
  type: "text" | "email" | "number" | "select";
  required: boolean;
  placeholder?: LocaleMap | null;
  help_text?: LocaleMap | null;
  help_images?: HelpImage[] | null;
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
  // A condition the buyer must see before paying (a one-off bonus, a level
  // cap), already in the request's locale. Optional for the same prerender
  // reason; absent or null means none.
  notice?: SkuNotice | null;
  display_price: PriceOut | null;
}

export interface SkuNotice {
  /** One or two words for the tile; absent when the text alone says it. */
  badge?: string | null;
  text: string;
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
  /** This locale's own search copy (never another locale's); absent from an older API. */
  seo_title?: string | null;
  seo_description?: string | null;
  // A game's regions are brands linked to its main brand (ADR-0099). Optional:
  // the build prerenders against the deployed API, which may predate them —
  // read through `?? "global"` / `?? null` / `?? []`.
  /** "global" on a main brand, else the region ("ru", "ph"…). */
  region_code?: string;
  /** The main brand's slug when this brand is a region of it. */
  region_of?: string | null;
  /** Every sellable region of the game, main brand first, in switcher order;
   *  empty when the game is sold in one region only. */
  regions?: BrandRegion[];
  /** While the brand is in maintenance: where the same goods are on sale.
   *  Optional — absent from an API that predates it; read through `?? null`. */
  maintenance_redirect?: BrandRedirect | null;
  /** Every way to buy this game, each its own page, main one first; empty when
   *  there is one. Optional — absent from an older API; read through `?? []`. */
  variants?: BrandVariant[];
}

export interface BrandVariant {
  /** `id`, `promo` — named from the message catalogue (`variants.<code>`). */
  code: string;
  slug: string;
}

export interface BrandRedirect {
  slug: string;
  name: string;
  short_description?: string | null;
}

export interface BrandRegion {
  code: string;
  slug: string;
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

export async function getBrands(
  locale: string,
  category?: string,
  opts?: { variants?: boolean },
): Promise<BrandSummary[]> {
  const params = new URLSearchParams();
  if (category && category !== "all") params.set("category", category);
  // A game's secondary variant pages (Standoff 2's promo codes) are not
  // catalogue tiles, but the sitemap and the static build need them.
  if (opts?.variants) params.set("variants", "true");
  const q = params.size > 0 ? `?${params.toString()}` : "";
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
    const items = await getBrands("ru", undefined, { variants: true });
    return items.map((b) => b.slug);
  } catch {
    return [];
  }
}
