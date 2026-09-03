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
