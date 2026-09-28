/**
 * Skins pricing admin — DTOs and calls for `/admin/skins/pricing` and `/admin/skins/items`
 * (`apps/api/src/yupay/modules/skins/{admin,pricing,schemas}.py`). Decimals travel as
 * strings both ways; the server validates (brackets ascend from 0, liquidity bands descend
 * to 0) and answers 422 with a `detail` the page shows as is.
 */

import { ApiError, apiGet, apiPatch, apiPut } from "@/lib/api";

export interface Bracket {
  from_usd: string;
  percent: string;
}

export interface LiquidityBand {
  min_count: number;
  pp: string;
}

export interface PricingRules {
  expenses_percent: string;
  retail: Bracket[];
  b2b: Bracket[];
  liquidity: LiquidityBand[];
  category_pp: Record<string, string>;
  weapon_pp: Record<string, string>;
  min_margin_usd: string;
  price_floor_usd: string;
  uzs_round_to: number;
  cap_at_steam: boolean;
}

export interface SkinsPricingOut {
  rules: PricingRules;
  enabled: boolean;
  sync_enabled: boolean;
  categories: string[];
}

export interface SkinQuoteOut {
  price_usd: string;
  cost_usd: string;
  expenses_usd: string;
  bracket_margin_usd: string;
  category_pp: string;
  weapon_pp: string;
  liquidity_pp: string;
  item_pp: string;
  effective_percent: string;
  applied: string;
}

export interface AdminSkinItemOut {
  slug: string;
  name: string;
  category: string;
  weapon: string | null;
  image_url: string | null;
  count_auto: number;
  cost_usd: string | null;
  sell_price_usd: string | null;
  margin_override_pp: string | null;
  fixed_price_usd: string | null;
}

export interface AdminSkinItemsOut {
  items: AdminSkinItemOut[];
}

export interface ItemPricingIn {
  margin_override_pp?: string | null;
  fixed_price_usd?: string | null;
}

const BASE = "/api/v1/admin/skins";

export const getPricing = () => apiGet<SkinsPricingOut>(`${BASE}/pricing`);

export const putPricing = (rules: PricingRules, key: string) =>
  apiPut<SkinsPricingOut>(`${BASE}/pricing`, rules, { "Idempotency-Key": key });

export function previewPrice(params: Record<string, string>): Promise<SkinQuoteOut> {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v.trim() !== ""));
  return apiGet<SkinQuoteOut>(`${BASE}/pricing/preview?${qs.toString()}`);
}

export function findItems(q: string, overridden: boolean): Promise<AdminSkinItemsOut> {
  const qs = new URLSearchParams({ limit: "20" });
  if (q.trim()) qs.set("q", q.trim());
  if (overridden) qs.set("overridden", "true");
  return apiGet<AdminSkinItemsOut>(`${BASE}/items?${qs.toString()}`);
}

export const patchItem = (slug: string, body: ItemPricingIn, key: string) =>
  apiPatch<ItemPricingIn>(`${BASE}/items/${encodeURIComponent(slug)}`, body, {
    "Idempotency-Key": key,
  });

/** A refusal in words: the API's `detail` (a string, or FastAPI's list of field errors). */
export function refusal(err: unknown): string {
  if (!(err instanceof ApiError)) return err instanceof Error ? err.message : String(err);
  const detail = (err.body as { detail?: unknown } | null)?.detail; // problem+json, narrowed below
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const msg = d && typeof d === "object" ? (d as { msg?: unknown }).msg : undefined;
        return typeof msg === "string" ? msg : "";
      })
      .filter(Boolean)
      .join("; ");
  }
  return err.message;
}
