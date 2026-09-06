/** Types mirroring the backend's admin-side catalog DTOs.
 *
 * Hand-written for now; once the FastAPI side stops moving daily we'll switch to the
 * generated `@yupay/api-client` and delete this file.
 */

export type Locale = "ru" | "en" | "uz";

export interface Translation {
  locale: Locale;
  name: string;
  short_description?: string | null;
  description?: string | null;
  instructions?: string | null;
  /** Short localized value-prop chips shown on the brand hero (e.g. "0%
   *  комиссии", "Оплата в сумах"). Brand-only — categories/products ignore it. */
  highlights?: string[];
}

export interface CategoryTranslation {
  locale: Locale;
  name: string;
  description?: string | null;
}

export interface Category {
  id: string;
  slug: string;
  icon: string | null;
  sort_order: number;
  active: boolean;
  translations: CategoryTranslation[];
}

export interface Brand {
  id: string;
  slug: string;
  category_id: string;
  logo_url: string | null;
  hero_image_url: string | null;
  accent_color: string | null;
  sort_order: number;
  active: boolean;
  maintenance: boolean;
  /** Brand-level B2B (merchant catalog) visibility. Read-only here — writes
   *  go through `PATCH /admin/catalog/brands/{id}/b2b` (see `../b2b.ts`);
   *  the plain brand PATCH ignores it. Effective B2B visibility is
   *  `brand.visible_b2b AND sku.visible_b2b`. */
  visible_b2b: boolean;
  translations: Translation[];
}

export interface FaqTranslation {
  locale: Locale;
  question: string;
  answer: string;
}

export interface BrandFaq {
  id: string;
  brand_id: string;
  sort_order: number;
  active: boolean;
  translations: FaqTranslation[];
}

export type ProductKind = "top_up" | "voucher";
export type FieldType = "text" | "email" | "number" | "select";

export interface FormOption {
  value: string;
  label: Record<string, string>;
}

/** Opts a field into a live "Проверить" lookup against the supplier before
 *  checkout — see `FieldCheck` on the API. `server_field` names the sibling
 *  field (e.g. `server`) whose value is sent alongside this one; leave unset
 *  when the game needs only the id. Not every supplier's check is honest:
 *  G2B rubber-stamps any input as valid for miHoYo titles (Genshin, Honkai
 *  Star Rail) — confirm live against the real API before wiring this up on
 *  a new game, a "valid" that verifies nothing is worse than no checker. */
export interface FieldCheck {
  provider: "g2b" | "waxpeer";
  server_field?: string | null;
}

export interface FormField {
  key: string;
  label: Record<string, string>;
  type: FieldType;
  required: boolean;
  placeholder?: Record<string, string> | null;
  help_text?: Record<string, string> | null;
  pattern?: string | null;
  options?: FormOption[] | null;
  check?: FieldCheck | null;
}

export interface Product {
  id: string;
  slug: string;
  brand_id: string;
  kind: ProductKind;
  supplier_hint: string | null;
  image_url: string | null;
  sort_order: number;
  active: boolean;
  required_fields: FormField[];
  translations: Translation[];
}

export interface SkuPriceOverride {
  currency: string;
  price: string;
}

export interface Sku {
  id: string;
  product_id: string;
  sku_code: string;
  denomination: string | null;
  region: string | null;
  price_usd: string;
  /** Wholesale cost paid to the supplier in USDT — drives the bulk
   *  UZS-price calculation and per-SKU margin reporting. Nullable for
   *  legacy SKUs created before the field existed. */
  cost_usdt: string | null;
  /** The margin price_usd is meant to hold above cost_usdt — the supplier
   *  price-refresh job re-derives price_usd from this whenever cost_usdt
   *  moves, so a SKU nobody is actively re-pricing never quietly starts
   *  selling below cost. Null means no margin is on file yet. */
  margin_percent: string | null;
  /** Steam-wallet-style SKUs: the customer picks the amount at checkout, so
   *  `price_usd` is a placeholder and these four drive the real price. */
  variable_amount: boolean;
  min_amount_usd: string | null;
  max_amount_usd: string | null;
  /** Admin-only: the margin. Never sent to public endpoints. */
  rate_multiplier: string | null;
  /** Unit-SKU (Telegram Stars) quantity bounds — both set or both null. See
   *  `ck_skus_qty_bounds_complete` on the API. */
  min_qty: number | null;
  max_qty: number | null;
  image_url: string | null;
  sort_order: number;
  active: boolean;
  /** SKU-level B2B (merchant catalog) visibility and markup. Read-only
   *  here — writes go through `PATCH /admin/catalog/skus/{id}/b2b` (see
   *  `../b2b.ts`); the plain SKU PATCH ignores both. The markup is margin
   *  data, same sensitivity as `rate_multiplier` — admin-only. */
  visible_b2b: boolean;
  b2b_markup_pct: string;
  price_overrides: SkuPriceOverride[];
}
