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

export interface FormField {
  key: string;
  label: Record<string, string>;
  type: "text" | "email" | "number" | "select";
  required: boolean;
  placeholder?: Record<string, string> | null;
  help_text?: Record<string, string> | null;
  pattern?: string | null;
  options?: FormOption[] | null;
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
    publisher: b.short_description ?? "",
    category: bucketCategory(b.category_slug),
    category_slug: b.category_slug,
    logoUrl: b.logo_url ?? undefined,
    bgUrl: b.hero_image_url ?? undefined,
    color: b.accent_color ?? "#3b82f6",
    inputType: "text",
    inputPlaceholder: locale === "ru" ? "Введите ID аккаунта" : "Account ID",
  };
}

export interface CategoryListItem {
  id: string;
  slug: string;
  name: string;
  icon: string | null;
}

export function useCategoriesList() {
  return useQuery<CategoryListItem[]>({
    queryKey: ["catalog", "categories"],
    queryFn: async () => {
      const data = await apiGet<{ items: CategoryApi[] }>(
        "/api/v1/catalog/categories",
        true,
      );
      return data.items.map((c) => ({
        id: c.id,
        slug: c.slug,
        name: c.name,
        icon: c.icon,
      }));
    },
    staleTime: 5 * 60_000,
  });
}

export interface Package {
  id: string; // sku id
  sku_code: string;
  amount: number;
  label: string;
  region: string | null;
  priceUsd: number;
  displayPrice: { amount: number; currency: string } | null;
  imageUrl: string | null;
}

function skuToPackage(sku: SkuApi): Package {
  const denomination = sku.denomination ?? sku.sku_code;
  const amountMatch = denomination.match(/\d+/);
  const amount = amountMatch ? Number.parseInt(amountMatch[0], 10) : 0;
  const priceUsd = Number.parseFloat(sku.price_usd) || 0;
  const displayPrice = sku.display_price
    ? {
        amount: Number.parseFloat(sku.display_price.amount) || 0,
        currency: sku.display_price.currency,
      }
    : null;
  return {
    id: sku.id,
    sku_code: sku.sku_code,
    amount,
    label: denomination,
    region: sku.region,
    priceUsd,
    displayPrice,
    imageUrl: sku.image_url,
  };
}

// --- queries --------------------------------------------------------------

export function useGames() {
  return useQuery<Game[]>({
    queryKey: ["catalog", "brands"],
    queryFn: async () => {
      const data = await apiGet<{ items: BrandApi[] }>(
        "/api/v1/catalog/brands",
        true,
      );
      return data.items.map((b) => brandToGame(b));
    },
    staleTime: 5 * 60_000,
  });
}

/**
 * Full brand payload: products + their SKUs. ``gameId`` is the brand slug.
 * The miniapp shows the brand's first active product's SKUs as packages.
 */
export function useBrandWithPrimaryProduct(
  gameId: string | undefined,
  currency = "USD",
) {
  return useQuery({
    queryKey: ["catalog", "brand", gameId, currency],
    enabled: Boolean(gameId),
    queryFn: async () => {
      const brand = await apiGet<BrandDetailApi>(
        `/api/v1/catalog/brands/${gameId ?? ""}`,
        true,
      );
      const firstProduct = brand.products.find((p) => true) ?? null;
      if (!firstProduct) {
        return {
          brand,
          product: null,
          packages: [] as Package[],
        };
      }
      const params = currency && currency !== "USD" ? `?currency=${currency}` : "";
      const product = await apiGet<ProductDetailApi>(
        `/api/v1/catalog/products/${firstProduct.slug}${params}`,
        true,
      );
      return {
        brand,
        product,
        packages: product.skus.map(skuToPackage),
      };
    },
    staleTime: 2 * 60_000,
  });
}
