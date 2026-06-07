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

export interface FormField {
  key: string;
  label: Record<string, string>;
  type: FieldType;
  required: boolean;
  placeholder?: Record<string, string> | null;
  help_text?: Record<string, string> | null;
  pattern?: string | null;
  options?: FormOption[] | null;
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
  image_url: string | null;
  sort_order: number;
  active: boolean;
  price_overrides: SkuPriceOverride[];
}
