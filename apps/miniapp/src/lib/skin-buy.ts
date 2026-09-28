/**
 * The pure half of buying a CS2 skin in the mini app: the API's 422s turned
 * into what the panel does next (show a moved price, move to the next offer,
 * flag the trade link), the sticky order key, and the trade-link shape and
 * check verdict. Mirrors `apps/web/src/lib/skin-checkout.ts` and
 * `SkinTradeLinkField.tsx`; kept apart from the panel so this app's node-only
 * Vitest suite can pin it.
 */

import { ApiError } from "./api";

import type { TradeLinkVerdict } from "./skins";

export interface NextOffer {
  listing_id: number;
  price_usd: string;
}

export type SkinBuyFailure =
  | { kind: "priceChanged"; expectedUsd: string }
  | { kind: "listingGone"; next: NextOffer | null }
  | { kind: "tradelink"; reason: "tradelink_other_account" | "invalid" };

function extraOf(err: ApiError): Record<string, unknown> | null {
  if (!err.body || typeof err.body !== "object") return null;
  const extra = (err.body as { extra?: unknown }).extra; // problem+json, narrowed below
  return extra && typeof extra === "object" ? (extra as Record<string, unknown>) : null;
}

function nextOfferOf(raw: unknown): NextOffer | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>; // trusted server JSON, narrowed below
  return typeof o.listing_id === "number" && typeof o.price_usd === "string"
    ? { listing_id: o.listing_id, price_usd: o.price_usd }
    : null;
}

/** The 422s of `skins.checkout.price_skin_line`; `null` for anything else. */
export function skinBuyFailure(err: unknown): SkinBuyFailure | null {
  if (!(err instanceof ApiError) || err.status !== 422) return null;
  const extra = extraOf(err);
  if (!extra) return null;
  if (typeof extra.expected_amount_usd === "string") {
    return { kind: "priceChanged", expectedUsd: extra.expected_amount_usd };
  }
  if (extra.reason === "listing_gone") {
    return { kind: "listingGone", next: nextOfferOf(extra.next_offer) };
  }
  if (extra.reason === "tradelink_other_account" || extra.reason === "invalid") {
    return { kind: "tradelink", reason: extra.reason };
  }
  return null;
}

export interface OrderKey {
  listingId: number;
  tradelink: string;
  key: string;
}

/**
 * One order key per offer and trade link: a retry of the same purchase replays,
 * another offer — or another link — is a new order. The server replays a keyed
 * order whatever the body says, so a key that outlived a link change would
 * deliver the skin to the old link.
 */
export function orderKeyFor(
  current: OrderKey | null,
  listingId: number,
  tradelink: string,
  mint: () => string,
): OrderKey {
  return current?.listingId === listingId && current.tradelink === tradelink
    ? current
    : { listingId, tradelink, key: mint() };
}

const LINK_SHAPE =
  /^https:\/\/steamcommunity\.com\/tradeoffer\/new\/\?partner=\d{1,12}&token=[\w-]{6,16}$/;

export function tradeLinkShapeOk(url: string): boolean {
  return LINK_SHAPE.test(url.trim());
}

export type TradeLinkLine = "ok" | "invalid" | "private" | "trade_ban" | "hold";

/**
 * What the field says about a checked link, and whether it may be paid for.
 * The check is advisory: `unavailable` — or no answer at all — never blocks.
 */
export function tradeLinkVerdict(v: TradeLinkVerdict | null): {
  line: TradeLinkLine | null;
  usable: boolean;
} {
  if (v === null || v.reason === "unavailable") return { line: null, usable: true };
  if (v.ok) return { line: "ok", usable: true };
  return { line: v.reason ?? "invalid", usable: false };
}

/** The cheapest offer by its dollar price (what the API bills); `null` when there are none. */
export function cheapestOffer<T extends { price_usd: string }>(offers: readonly T[]): T | null {
  let best: T | null = null;
  for (const o of offers) {
    if (best === null || Number(o.price_usd) < Number(best.price_usd)) best = o;
  }
  return best;
}

/**
 * The page after a sold offer: the offer gone, and the server's next offer
 * selected — or, when that one is not on the page, the cheapest left — so the
 * notice and the button name the same offer.
 */
export function afterListingGone<T extends { listing_id: number; price_usd: string }>(
  offers: readonly T[],
  soldId: number,
  next: NextOffer | null,
): { offers: T[]; selected: T | null } {
  const rest = offers.filter((o) => o.listing_id !== soldId);
  const named = rest.find((o) => o.listing_id === next?.listing_id);
  return { offers: rest, selected: named ?? cheapestOffer(rest) };
}
