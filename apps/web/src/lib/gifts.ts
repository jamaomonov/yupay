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
   *  priced from its zone. Optional, like `zones`/`zone_default` below:
   *  `apiGet` trusts the response shape with an unchecked cast (`api.ts`),
   *  so a 200 from an API version that predates this field (a rolling
   *  deploy skew window, not just a 404 dark-deploy) still resolves this
   *  promise — it does not raise for `getGiftDetail`'s try/catch to catch.
   *  Every read site must treat a missing/empty `regions` the same as "no
   *  price for the default zone" and degrade, never throw. */
  regions?: GiftRegion[];
  region_default?: string;
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

/* ---------------------------------------------------------------------- *
 * Pre-purchase recipient check (`GET /gifts/steam-profile`)
 * ---------------------------------------------------------------------- */

/** The four verdicts the endpoint can return (mirrors `GiftProfileOut`).
 *
 *  They are deliberately not equally weighted: only `not_found` — Steam
 *  itself answering that no such profile exists — is a fact about the
 *  recipient. `unsupported` (an `s.team` friend-invite token the Steam Web
 *  API cannot resolve at all) and `unavailable` (no API key, an outage, a
 *  timeout) are facts about *us*, and must never stand between the buyer and
 *  Pay. See `profileCheckBlocks`. */
export type GiftProfileStatus = "found" | "not_found" | "unsupported" | "unavailable";

/** Wire shape of `GiftProfileOut` — see `yupay.modules.gifts.schemas`. */
interface GiftProfileWire {
  status: GiftProfileStatus;
  steam_id: string | null;
  nickname: string | null;
  avatar_url: string | null;
}

/** The verdict as the UI consumes it. `found` is narrowed to carry a real
 *  nickname so a confirmation card can never render around an empty name —
 *  the one shape of this feature that would be worse than not shipping it,
 *  since it reassures the buyer without having confirmed anything. */
export type GiftProfileCheck =
  | { status: "found"; nickname: string; avatarUrl: string | null }
  | { status: "not_found" | "unsupported" | "unavailable" };

/**
 * Resolve a pasted Steam link into "who is this, actually?".
 *
 * **Never throws and never rejects.** Any failure — network, our own 5xx, a
 * 429, a 422 for a link the server parses more strictly than the client-side
 * gate does — folds into `unavailable`, which is non-blocking. That is the
 * whole point: this check is a second pair of eyes, and a check that fails on
 * our side must not cost a sale. The server holds the same line (see
 * `yupay.modules.gifts.profile`), so this is belt-and-braces, not the only
 * guard.
 *
 * Public data about a link the buyer just typed, so `anonymous: true` — no
 * bearer token is attached to a call that does not need one.
 */
export async function checkGiftProfile(inviteUrl: string): Promise<GiftProfileCheck> {
  try {
    const out = await apiFetch<GiftProfileWire>(
      `/gifts/steam-profile?invite_url=${encodeURIComponent(inviteUrl)}`,
      { anonymous: true },
    );
    if (out.status !== "found") return { status: out.status };
    // The API contract says `found` always carries a persona (it returns
    // `unavailable` when Steam gave it nothing to show). If that ever stopped
    // holding, a nameless "confirmation" is the worst answer available — so it
    // degrades to the non-blocking status rather than to a blank green card.
    if (!out.nickname) return { status: "unavailable" };
    return { status: "found", nickname: out.nickname, avatarUrl: out.avatar_url };
  } catch {
    return { status: "unavailable" };
  }
}

/**
 * Whether a verdict stands between the buyer and Pay. Only a definitive
 * `not_found` does.
 *
 * Deliberately the opposite of `blocksCheckout` in `player-check-state.ts`,
 * where an *unchecked* id also blocks: there the check is a required gate on
 * a top-up that would otherwise go to the wrong account with no way back;
 * here it is an optional second look, and `null` (never checked) leaves the
 * purchase exactly as available as it was before the button existed.
 */
export function profileCheckBlocks(check: GiftProfileCheck | null): boolean {
  return check?.status === "not_found";
}
