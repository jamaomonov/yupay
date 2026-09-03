/**
 * Steam Gifts catalog data access — the public storefront section
 * `/store/steam-gifts`. DTOs mirror `yupay.modules.gifts.schemas`; money
 * travels as display strings straight from the API, same convention as
 * `lib/catalog.ts`.
 *
 * The whole `/gifts/*` surface 404s while `steam_gifts_enabled` is off (see
 * `_ensure_enabled` in the API's `gifts/routes.py`), and the deployed API can
 * predate this feature entirely — the same "dark deploy" situation
 * `getBrandSlugs` in `lib/catalog.ts` already handles. So the two server
 * fetchers below never throw: any error (network, 404, or otherwise)
 * collapses to an empty result, never a broken build or a 500 page.
 */
import { apiGet } from "./api";
import { apiFetch } from "./client";

export interface GiftApp {
  app_id: number;
  name: string;
  image: string | null;
  type: string;
  price_usd: string | null;
  price_uzs: string | null;
  discount_percent: number | null;
  packages_count: number;
  dlc_count: number;
}

export interface GiftsList {
  items: GiftApp[];
  total: number;
}

export interface GiftZonePrice {
  zone: string;
  price_usd: string;
  price_uzs: string | null;
}

export interface GiftPackage {
  id: number;
  name: string;
  image: string | null;
  discount_percent: number | null;
  prices: GiftZonePrice[];
}

/** One purchasable country, priced from the zone that covers it — the
 *  country picker's own unit. Mirrors `GiftRegionOut`; see
 *  `yupay.modules.gifts.service.ZONE_COUNTRIES` for which countries a zone
 *  covers. Every country sharing a zone carries that zone's identical
 *  price. */
export interface GiftRegion {
  country: string;
  zone: string;
  price_usd: string;
  price_uzs: string | null;
}

export interface GiftAppDetail extends GiftApp {
  description: string | null;
  packages: GiftPackage[];
  dlc_total: number;
  /** The country picker (2026-09-03): `region_default` first, each entry
   *  priced from its zone. */
  regions: GiftRegion[];
  region_default: string;
  /** Deprecated (2026-09-03) — the zone-label picker `regions` replaced.
   *  Optional so a build against an older deployed API (predating this
   *  field) still type-checks; new code reads `regions`/`region_default`
   *  instead. */
  zones?: string[];
  zone_default?: string;
}

const REVALIDATE = 300;

/** Curated hot-offer strip (pinned apps + best current discounts). `[]` on
 *  any error — network, or a 404 while the feature flag is off / on an API
 *  build that predates it. */
export async function getGiftsHot(locale: string): Promise<GiftApp[]> {
  try {
    const r = await apiGet<GiftsList>("/gifts/catalog/hot", {
      locale,
      revalidate: REVALIDATE,
      tags: ["gifts"],
    });
    return r.items;
  } catch {
    return [];
  }
}

/** One page of the default (no-search) catalog listing. `{items:[],total:0}`
 *  on any error, for the same reason as `getGiftsHot`. */
export async function getGiftsPage(locale: string, offset = 0): Promise<GiftsList> {
  try {
    return await apiGet<GiftsList>(`/gifts/catalog?offset=${String(offset)}`, {
      locale,
      revalidate: REVALIDATE,
      tags: ["gifts"],
    });
  } catch {
    return { items: [], total: 0 };
  }
}

/**
 * Client-side search + pagination, used by `GiftsBrowser` via TanStack
 * Query. Public catalog data — `anonymous: true` so a signed-in visitor's
 * bearer token isn't attached to a call that doesn't need it.
 *
 * Unlike the two fetchers above, this one is allowed to throw: it runs
 * behind React Query, which has its own loading/error UI, and swallowing the
 * error here would just make a failed search look like an empty one.
 */
export function searchGifts(locale: string, q: string, offset: number): Promise<GiftsList> {
  const params = new URLSearchParams({ offset: String(offset) });
  const query = q.trim();
  if (query) params.set("search", query);
  return apiFetch<GiftsList>(`/gifts/catalog?${params.toString()}`, {
    anonymous: true,
    headers: { "Accept-Language": locale },
  });
}

/**
 * One app's full detail: packages priced per offered zone, plus the DLC
 * count. Server fetcher — same dark-deploy-safe contract as `getGiftsHot`/
 * `getGiftsPage` above: any error (network, a 404 for an unknown app id, or
 * the whole `/gifts/*` surface 404ing while the feature flag is off)
 * collapses to `null` rather than throwing. The page calls `notFound()`
 * itself when this comes back `null`.
 */
export async function getGiftDetail(locale: string, appId: number): Promise<GiftAppDetail | null> {
  try {
    return await apiGet<GiftAppDetail>(`/gifts/catalog/${String(appId)}`, {
      locale,
      revalidate: REVALIDATE,
      tags: ["gifts"],
    });
  } catch {
    return null;
  }
}

/**
 * Client-side search + pagination over one app's DLC list, used by
 * `DlcBrowser`. Mirrors `searchGifts`: public data, so `anonymous: true`,
 * and allowed to throw — `DlcBrowser` has its own loading/error UI.
 */
export function fetchGiftDlc(
  locale: string,
  appId: number,
  q: string,
  offset: number,
): Promise<GiftsList> {
  const params = new URLSearchParams({ offset: String(offset) });
  const query = q.trim();
  if (query) params.set("search", query);
  return apiFetch<GiftsList>(`/gifts/catalog/${String(appId)}/dlc?${params.toString()}`, {
    anonymous: true,
    headers: { "Accept-Language": locale },
  });
}
