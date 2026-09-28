import { apiGet, apiGetOrNull } from "@/lib/api";
import { apiFetch } from "@/lib/client";
import { formatUzs } from "@/lib/seo";
import type { SkinDetail, SkinFacets, SkinListings, SkinQuery, SkinsPage } from "@yupay/utils";

export {
  DEFAULT_SORT,
  EXTERIORS,
  SKIN_CATEGORIES,
  parseSkinQuery,
  skinQueryString,
} from "@yupay/utils";
export type {
  SkinSort,
  Exterior,
  SkinCategory,
  SkinItem,
  SkinsPage,
  Facet,
  SkinFacets,
  SkinFamilyMember,
  SkinDetail,
  SkinListing,
  SkinListings,
  SkinQuery,
  SkinQueryPatch,
} from "@yupay/utils";

function apiParams(q: SkinQuery): string {
  const p = new URLSearchParams();
  if (q.category) p.set("category", q.category);
  if (q.weapon) p.set("weapon", q.weapon);
  if (q.exterior) p.set("exterior", q.exterior);
  if (q.rarity) p.set("rarity", q.rarity);
  if (q.stattrak) p.set("stattrak", "true");
  if (q.q) p.set("q", q.q);
  if (q.minUzs !== undefined) p.set("min_uzs", String(q.minUzs));
  if (q.maxUzs !== undefined) p.set("max_uzs", String(q.maxUzs));
  p.set("sort", q.sort);
  if (q.cursor) p.set("cursor", q.cursor);
  p.set("limit", "48");
  return p.toString();
}

const OPTS = { revalidate: 60, tags: ["skins"] };

export async function getSkinsPage(locale: string, q: SkinQuery): Promise<SkinsPage> {
  try {
    return await apiGet<SkinsPage>(`/skins/catalog?${apiParams(q)}`, { locale, ...OPTS });
  } catch {
    return { items: [], next_cursor: null };
  }
}

/** Facets; with a category, weapons/wears/rarities are counted inside it. */
export async function getSkinFacets(locale: string, category?: string): Promise<SkinFacets | null> {
  const qs = category ? `?category=${encodeURIComponent(category)}` : "";
  try {
    return await apiGetOrNull<SkinFacets>(`/skins/facets${qs}`, { locale, ...OPTS });
  } catch {
    return null;
  }
}

/**
 * `null` only on a real 404. Any other failure throws to the error boundary: a
 * swallowed outage rendered "not found", which tells search engines the page is gone.
 */
export async function getSkinDetail(locale: string, slug: string): Promise<SkinDetail | null> {
  return apiGetOrNull<SkinDetail>(`/skins/${encodeURIComponent(slug)}`, { locale, ...OPTS });
}

export async function fetchSkinListings(slug: string): Promise<SkinListings> {
  return apiFetch<SkinListings>(`/skins/${encodeURIComponent(slug)}/listings`, { anonymous: true });
}

/**
 * The price to print: soʻm when the API could convert, dollars when FX was down,
 * `null` only when there is no price at all (sold out). Keyed on the dollar
 * figure so an FX outage never reads as "out of stock".
 */
export function displayPrice(
  locale: string,
  priceUzs: string | null,
  priceUsd: string | null,
): string | null {
  if (priceUsd === null) return null;
  if (priceUzs !== null) return formatUzs(locale, Math.round(Number(priceUzs)));
  return `$${priceUsd}`;
}

/** The signed-in customer's saved trade link, or `null`. */
export async function getTradeLink(): Promise<string | null> {
  const out = await apiFetch<{ url: string | null }>("/skins/tradelink");
  return out.url;
}

export async function saveTradeLink(url: string): Promise<void> {
  await apiFetch("/skins/tradelink", {
    method: "PUT",
    body: { url },
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
}

export type TradeLinkReason = "invalid" | "private" | "trade_ban" | "hold" | "unavailable";
export interface TradeLinkVerdict {
  ok: boolean;
  reason: TradeLinkReason | null;
}

/** Advisory pre-purchase check; `unavailable` never blocks. */
export async function checkTradeLink(url: string): Promise<TradeLinkVerdict> {
  return apiFetch<TradeLinkVerdict>("/skins/tradelink/check", {
    method: "POST",
    body: { url },
    anonymous: true,
  });
}
