import { apiGet, apiGetOrNull } from "@/lib/api";
import { apiFetch } from "@/lib/client";

export type SkinSort = "price" | "-price" | "discount" | "popular";
export type Exterior = "FN" | "MW" | "FT" | "WW" | "BS";

export const SKIN_CATEGORIES = [
  "rifles",
  "pistols",
  "smgs",
  "heavy",
  "knives",
  "gloves",
  "agents",
  "cases",
  "keys",
  "music-kits",
  "charms",
] as const;
export type SkinCategory = (typeof SKIN_CATEGORIES)[number];
const SORTS: readonly SkinSort[] = ["price", "-price", "discount", "popular"];
/** What the market opens on: the items people actually buy, not a page of $0.20 floor stickers. */
export const DEFAULT_SORT: SkinSort = "popular";
const EXTERIORS: readonly Exterior[] = ["FN", "MW", "FT", "WW", "BS"];

export interface SkinItem {
  slug: string;
  name: string;
  phase: string | null;
  category: string;
  weapon: string | null;
  skin: string | null;
  exterior: Exterior | null;
  stattrak: boolean;
  souvenir: boolean;
  rarity: string | null;
  rarity_color: string | null;
  image_url: string | null;
  price_usd: string | null;
  price_uzs: string | null;
  steam_price_usd: string | null;
  discount_percent: number | null;
  count: number;
  min_float: string | null;
  max_float: string | null;
}
export interface SkinsPage {
  items: SkinItem[];
  next_cursor: string | null;
}
export interface Facet {
  value: string;
  count: number;
}
export interface SkinFacets {
  categories: Facet[];
  weapons: Facet[];
  exteriors: Facet[];
  rarities: Facet[];
}
export interface SkinFamilyMember {
  slug: string;
  exterior: Exterior | null;
  stattrak: boolean;
  souvenir: boolean;
  price_usd: string | null;
  price_uzs: string | null;
  count: number;
}
export interface SkinDetail extends SkinItem {
  cheapest: { listing_id: number; price_usd: string; price_uzs: string | null }[];
  family: SkinFamilyMember[];
}
export interface SkinListing {
  listing_id: number;
  price_usd: string;
  price_uzs: string | null;
  float_value: number | null;
  paint_seed: number | null;
  stickers: { name: string; image: string | null; slot: number | null; wear: number | null }[];
  inspect_url: string | null;
}
export interface SkinListings {
  items: SkinListing[];
  degraded: boolean;
}

export interface SkinQuery {
  category?: SkinCategory;
  weapon?: string;
  exterior?: Exterior;
  rarity?: string;
  stattrak?: boolean;
  q?: string;
  minUzs?: number;
  maxUzs?: number;
  sort: SkinSort;
  cursor?: string;
}

type Params = Record<string, string | string[] | undefined>;
/** First value of a possibly repeated param, trimmed; an empty one counts as absent. */
function first(v: string | string[] | undefined): string | undefined {
  const text = (Array.isArray(v) ? v[0] : v)?.trim();
  return text === undefined || text === "" ? undefined : text;
}
const SAFE_TEXT = /^[\p{L}\p{N} .|'™★()&-]{1,80}$/u;
const CURSOR = /^[A-Za-z0-9_-]{1,200}$/;

function amount(v: string | undefined): number | undefined {
  if (v === undefined || !/^\d{1,12}$/.test(v)) return undefined;
  return Number(v);
}

export function parseSkinQuery(params: Params): SkinQuery {
  const q: SkinQuery = { sort: DEFAULT_SORT };
  const category = first(params.category);
  if (category && (SKIN_CATEGORIES as readonly string[]).includes(category)) {
    q.category = category as SkinCategory; // narrowed by the includes() check above
  }
  const weapon = first(params.weapon);
  if (weapon && SAFE_TEXT.test(weapon)) q.weapon = weapon;
  const exterior = first(params.exterior);
  if (exterior && (EXTERIORS as readonly string[]).includes(exterior)) {
    q.exterior = exterior as Exterior; // narrowed by the includes() check above
  }
  const rarity = first(params.rarity);
  if (rarity && SAFE_TEXT.test(rarity)) q.rarity = rarity;
  if (first(params.stattrak) === "1") q.stattrak = true;
  const text = first(params.q);
  if (text && SAFE_TEXT.test(text)) q.q = text;
  const min = amount(first(params.min));
  if (min !== undefined) q.minUzs = min;
  const max = amount(first(params.max));
  if (max !== undefined) q.maxUzs = max;
  const sort = first(params.sort);
  if (sort && (SORTS as readonly string[]).includes(sort)) q.sort = sort as SkinSort; // narrowed above
  const cursor = first(params.cursor);
  if (cursor && CURSOR.test(cursor)) q.cursor = cursor;
  return q;
}

const ORDER: readonly (keyof SkinQuery)[] = [
  "category",
  "weapon",
  "exterior",
  "rarity",
  "stattrak",
  "q",
  "minUzs",
  "maxUzs",
  "sort",
  "cursor",
];
const KEY: Record<keyof SkinQuery, string> = {
  category: "category",
  weapon: "weapon",
  exterior: "exterior",
  rarity: "rarity",
  stattrak: "stattrak",
  q: "q",
  minUzs: "min",
  maxUzs: "max",
  sort: "sort",
  cursor: "cursor",
};

/** A change to a query: a key set to `undefined` removes that filter. */
export type SkinQueryPatch = { [K in keyof SkinQuery]?: SkinQuery[K] | undefined };

export function skinQueryString(q: SkinQuery, patch: SkinQueryPatch = {}): string {
  const changesFilter = Object.keys(patch).some((k) => k !== "cursor");
  const merged: SkinQueryPatch = { ...q, ...patch };
  if (changesFilter && !("cursor" in patch)) delete merged.cursor;
  const out = new URLSearchParams();
  for (const key of ORDER) {
    const v = merged[key];
    if (v === undefined || v === "" || v === false) continue;
    if (key === "sort" && v === DEFAULT_SORT) continue;
    out.set(KEY[key], v === true ? "1" : String(v));
  }
  const s = out.toString();
  return s ? `?${s}` : "";
}

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

export async function getSkinFacets(locale: string): Promise<SkinFacets | null> {
  try {
    return await apiGetOrNull<SkinFacets>("/skins/facets", { locale, ...OPTS });
  } catch {
    return null;
  }
}

export async function getSkinDetail(locale: string, slug: string): Promise<SkinDetail | null> {
  try {
    return await apiGetOrNull<SkinDetail>(`/skins/${encodeURIComponent(slug)}`, {
      locale,
      ...OPTS,
    });
  } catch {
    return null;
  }
}

export async function fetchSkinListings(slug: string): Promise<SkinListings> {
  return apiFetch<SkinListings>(`/skins/${encodeURIComponent(slug)}/listings`, { anonymous: true });
}
