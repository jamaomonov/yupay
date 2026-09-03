/**
 * Steam Gifts catalog data access for the Mini App's native `/gifts` flow.
 *
 * DTOs mirror `yupay.modules.gifts.schemas` (same contract `apps/web/src/lib/gifts.ts`
 * consumes) — money travels as display strings straight from the API, never
 * parsed to a number except for display formatting (see `lib/currency.ts`).
 *
 * The whole `/gifts/*` surface 404s while `steam_gifts_enabled` is off. Every
 * fetcher below tolerates *that specific* 404 without throwing — a genuine
 * network failure or 5xx still throws, so `GiftsCatalog`/`GiftGame` can tell
 * "this feature isn't live" (silent empty/coming-soon state) apart from "the
 * request actually failed" (their own error+retry UI).
 */

import { apiGet, ApiError } from "./api";

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

export interface GiftAppDetail extends GiftApp {
  description: string | null;
  packages: GiftPackage[];
  dlc_total: number;
  zones: string[];
  zone_default: string;
}

const GIFTS_CATALOG = "/api/v1/gifts/catalog";

/** Runs `run`, swallowing only a 404 (the flag-off / dark-deploy shape) into
 *  `fallback`. Any other error (network failure, 5xx) still throws. */
async function safeOn404<T>(run: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await run();
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return fallback;
    throw err;
  }
}

/** Curated hot-offer strip (pinned apps + best current discounts). */
export function fetchGiftsHot(): Promise<GiftApp[]> {
  return safeOn404(async () => {
    const r = await apiGet<GiftsList>(`${GIFTS_CATALOG}/hot`, true);
    return r.items;
  }, []);
}

/** One page of the catalog listing, optionally filtered by `search`. */
export function fetchGiftsPage(offset: number, search?: string): Promise<GiftsList> {
  const params = new URLSearchParams({ offset: String(offset) });
  const query = search?.trim();
  if (query) params.set("search", query);
  return safeOn404(() => apiGet<GiftsList>(`${GIFTS_CATALOG}?${params.toString()}`, true), {
    items: [],
    total: 0,
  });
}

/** One app's full detail: packages priced per offered zone, plus the DLC
 *  count. `null` for an unknown app id, same as the whole-surface-off case —
 *  the caller (`GiftGame`) treats both as "nothing to show here". */
export function fetchGiftDetail(appId: number): Promise<GiftAppDetail | null> {
  return safeOn404(() => apiGet<GiftAppDetail>(`${GIFTS_CATALOG}/${String(appId)}`, true), null);
}

/** One page of an app's DLC list, optionally filtered by `q`. */
export function fetchGiftDlc(appId: number, q: string, offset: number): Promise<GiftsList> {
  const params = new URLSearchParams({ offset: String(offset) });
  const query = q.trim();
  if (query) params.set("search", query);
  return safeOn404(
    () => apiGet<GiftsList>(`${GIFTS_CATALOG}/${String(appId)}/dlc?${params.toString()}`, true),
    { items: [], total: 0 },
  );
}

export interface GiftPage {
  items: GiftApp[];
  total: number;
}

/**
 * Folds one fetched page onto the catalog's current accumulation. A fresh
 * query (`offset === 0`) replaces whatever was on screen; "Показать ещё"
 * (`offset > 0`) appends — mirrors `GiftsBrowser`'s accumulation semantics on
 * the web storefront, extracted here as a pure reducer so `GiftsCatalog`
 * only has to call it from its fetch-then-`setState` callback.
 */
export function accumulatePage(prev: GiftPage, page: GiftsList, offset: number): GiftPage {
  return {
    items: offset === 0 ? page.items : [...prev.items, ...page.items],
    total: page.total,
  };
}

// Steam invite-link shapes, mirroring `GiftPurchasePanel.tsx::isValidInviteUrl`
// on the web storefront exactly — same three accepted forms, same host/scheme
// rules. This is only a client-side gate (the server is the actual source of
// truth and canonicalizes on its own), so it doesn't need to match
// byte-for-byte, just reject the same obviously-wrong input.
const STEAM_ID64_RE = /^\d{17}$/;
const STEAM_VANITY_RE = /^[A-Za-z0-9_-]{2,32}$/;
const S_TEAM_PATH_RE = /^[A-Za-z0-9/_-]{1,64}$/;

/**
 * Validates + canonicalizes a Steam profile/invite link. Accepts a scheme-
 * optional bare host+path (assumed `https://`), but a *given* scheme must be
 * `https:`; the host is compared exactly (case-insensitively), never as a
 * suffix/substring match. Returns the canonical `https://` form on a match,
 * `null` otherwise.
 */
export function validateInviteUrl(raw: string): string | null {
  const value = raw.trim();
  if (!value) return null;
  const candidate = value.includes("://") ? value : `https://${value}`;
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    return null;
  }
  if (url.protocol !== "https:") return null;
  const host = url.hostname.toLowerCase();
  const parts = url.pathname.replace(/\/+$/, "").split("/").filter(Boolean);

  if (host === "steamcommunity.com") {
    if (parts.length === 2 && parts[0] === "profiles" && STEAM_ID64_RE.test(parts[1] ?? "")) {
      return `https://steamcommunity.com/profiles/${parts[1] ?? ""}`;
    }
    if (parts.length === 2 && parts[0] === "id" && STEAM_VANITY_RE.test(parts[1] ?? "")) {
      return `https://steamcommunity.com/id/${parts[1] ?? ""}`;
    }
    return null;
  }
  if (host === "s.team") {
    const tail = parts.slice(1).join("/");
    if (parts.length >= 2 && parts[0] === "p" && S_TEAM_PATH_RE.test(tail)) {
      return `https://s.team/p/${tail}`;
    }
    return null;
  }
  return null;
}

/**
 * Resolves the price of one package in one zone from an already-fetched
 * detail payload — no round trip on a package/region switch, same as the web
 * panel. `null` when nothing is selected yet, the package doesn't exist on
 * this detail, or it has no price in that zone.
 */
export function priceFor(
  detail: GiftAppDetail | null,
  packageId: number | null,
  zone: string | null,
): GiftZonePrice | null {
  if (!detail || packageId === null || zone === null) return null;
  const pkg = detail.packages.find((p) => p.id === packageId);
  if (!pkg) return null;
  return pkg.prices.find((p) => p.zone === zone) ?? null;
}
