/**
 * CS2 skins reads for the mini app. The query model and DTOs are shared with
 * the web storefront (`@yupay/utils`); this file only fetches and formats.
 *
 * Every `/skins/*` read 404s while the feature flag is off, so a 404 on the
 * facets is how the catalogue page knows to show its "coming soon" screen.
 */

import type { SkinDetail, SkinFacets, SkinListings, SkinQuery, SkinsPage } from "@yupay/utils";

import { apiGet, ApiError } from "./api";
import { formatMoney } from "./currency";

const SKINS = "/api/v1/skins";
const PAGE_SIZE = 24;

export function skinsApiParams(q: SkinQuery): string {
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
  p.set("limit", String(PAGE_SIZE));
  return p.toString();
}

async function nullOn404<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load();
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export function fetchSkinsPage(q: SkinQuery): Promise<SkinsPage> {
  return apiGet<SkinsPage>(`${SKINS}/catalog?${skinsApiParams(q)}`, true);
}

/** `null` while the feature is off. */
export function fetchSkinFacets(): Promise<SkinFacets | null> {
  return nullOn404(() => apiGet<SkinFacets>(`${SKINS}/facets`, true));
}

/** `null` only when the skin does not exist; an outage throws (the page offers a retry). */
export function fetchSkinDetail(slug: string): Promise<SkinDetail | null> {
  return nullOn404(() => apiGet<SkinDetail>(`${SKINS}/${encodeURIComponent(slug)}`, true));
}

export function fetchSkinListings(slug: string): Promise<SkinListings> {
  return apiGet<SkinListings>(`${SKINS}/${encodeURIComponent(slug)}/listings`, true);
}

/**
 * Soʻm when the API could convert, dollars when FX was down, `null` only when
 * there is no price at all. Keyed on the dollar figure so an FX outage never
 * reads as "sold out".
 */
export function skinPriceText(priceUzs: string | null, priceUsd: string | null): string | null {
  if (priceUsd === null) return null;
  if (priceUzs !== null) return formatMoney(Math.round(Number(priceUzs)), "UZS");
  return formatMoney(Number(priceUsd), "USD");
}
