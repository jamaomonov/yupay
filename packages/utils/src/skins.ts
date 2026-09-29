/**
 * The CS2 skins query model and API DTOs, shared by the web storefront and the
 * mini app: one parser, one serialiser, one set of whitelists for the URL.
 */

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
/** What the market opens on: knives and gloves first, as skinsavdo.uz does — `popular` opened on a wall of cases, `price` on $0.20 stickers. */
export const DEFAULT_SORT: SkinSort = "-price";
export const EXTERIORS: readonly Exterior[] = ["FN", "MW", "FT", "WW", "BS"];

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
  /** Rarity facets only: the grade's colour. */
  color?: string | null;
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
  /** The SKU to order this item under; `null` until skins are sellable. */
  buy_sku_id?: string | null;
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

/** The weapon rarity scale, high to low — what the catalogue offers before a category is picked. */
const WEAPON_RARITIES = [
  "Contraband",
  "Covert",
  "Classified",
  "Restricted",
  "Mil-Spec Grade",
  "Industrial Grade",
  "Consumer Grade",
] as const;

/** Categories where StatTrak™ exists: weapons, knives and music kits. */
const STATTRAK_CATEGORIES: ReadonlySet<SkinCategory> = new Set([
  "rifles",
  "pistols",
  "smgs",
  "heavy",
  "knives",
  "music-kits",
]);

export interface FilterSections {
  /** Wear filter: only where items have an exterior (not agents, cases, charms…). */
  wear: boolean;
  /** StatTrak™ toggle: only where StatTrak items exist. */
  stattrak: boolean;
  /** The rarity checkboxes to offer. */
  rarities: Facet[];
}

/**
 * Which filters make sense for the category picked — the way Waxpeer's panel changes
 * with it: a weapon category lists weapon rarities, agents list Master…Distinguished,
 * cases have no wear. The facets are already counted inside the category; with none
 * picked, the rarity list is the weapon scale rather than all seventeen grades of every
 * item type mixed together. A rarity already chosen (a shared link) is always kept.
 */
export function filterSections(
  category: SkinCategory | undefined,
  facets: SkinFacets,
  chosenRarity: string | undefined,
): FilterSections {
  const weaponScale: readonly string[] = WEAPON_RARITIES;
  const rarities =
    category === undefined
      ? facets.rarities.filter((r) => weaponScale.includes(r.value) || r.value === chosenRarity)
      : facets.rarities;
  return {
    wear: facets.exteriors.length > 0,
    stattrak: category === undefined || STATTRAK_CATEGORIES.has(category),
    rarities,
  };
}
