/**
 * Buy one CS2 skin listing: `POST /orders` (the `cs2-skin` SKU) then
 * `POST /payments/intents`, handing back where the browser goes next.
 *
 * The `gift-checkout` shape, narrower: a skin is signed-in only (a purchase
 * that falls through refunds to the YuPay balance, which a guest does not
 * have), one line per order, and the API's 422s are turned into typed errors
 * the panel can act on — a moved price, a sold listing with the next offer, a
 * trade link that is someone else's. Uses `apiFetch`, so an expired access
 * token is refreshed on the way.
 */
import { ApiError, apiFetch, getAccessToken } from "./client";
import { pathFor } from "./seo";

export interface BuySkinParams {
  locale: string;
  skuId: string;
  slug: string;
  listingId: number;
  tradelink: string;
  /** The offer's quoted price; the API bills its own, within ±2 % of this. */
  amountUsd: string;
  provider: string;
  /** Caller-owned `Idempotency-Key` for `POST /orders` (sticky across a retry). */
  orderKey: string;
}

export interface BuySkinResult {
  orderId: string;
  intentUrl: string | null;
  trackHref: string;
}

export interface NextOffer {
  listing_id: number;
  price_usd: string;
}

export class SignInRequiredError extends Error {
  constructor() {
    super("sign in to buy a skin");
    this.name = "SignInRequiredError";
  }
}

export class SkinPriceChangedError extends Error {
  constructor(public readonly expectedAmountUsd: string) {
    super("skin price changed");
    this.name = "SkinPriceChangedError";
  }
}

export class SkinListingGoneError extends Error {
  constructor(public readonly nextOffer: NextOffer | null) {
    super("skin listing gone");
    this.name = "SkinListingGoneError";
  }
}

export class SkinTradeLinkError extends Error {
  constructor(public readonly reason: string) {
    super("trade link refused");
    this.name = "SkinTradeLinkError";
  }
}

function nextOfferOf(raw: unknown): NextOffer | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>; // trusted server JSON, narrowed below
  return typeof o.listing_id === "number" && typeof o.price_usd === "string"
    ? { listing_id: o.listing_id, price_usd: o.price_usd }
    : null;
}

/** The 422s of `skins.checkout.price_skin_line` → typed errors; anything else rethrown. */
function skinError(err: unknown): unknown {
  if (!(err instanceof ApiError) || err.status !== 422 || !err.extra) return err;
  const { expected_amount_usd: expected, reason, next_offer: next } = err.extra;
  if (typeof expected === "string") return new SkinPriceChangedError(expected);
  if (reason === "listing_gone") return new SkinListingGoneError(nextOfferOf(next));
  if (reason === "tradelink_other_account" || reason === "invalid") {
    return new SkinTradeLinkError(reason);
  }
  return err;
}

export async function buySkin(params: BuySkinParams): Promise<BuySkinResult> {
  if (!getAccessToken()) throw new SignInRequiredError();
  let order: { id: string };
  try {
    order = await apiFetch<{ id: string }>("/orders", {
      method: "POST",
      headers: { "Idempotency-Key": params.orderKey, "Accept-Language": params.locale },
      body: {
        currency: "UZS",
        items: [
          {
            sku_id: params.skuId,
            qty: 1,
            amount_usd: params.amountUsd,
            fulfillment_data: {
              slug: params.slug,
              listing_id: params.listingId,
              tradelink: params.tradelink,
            },
          },
        ],
      },
    });
  } catch (err) {
    throw skinError(err);
  }
  const trackHref = pathFor(params.locale, `/orders/${order.id}`);
  const intent = await apiFetch<{ intent_url: string | null }>("/payments/intents", {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: {
      order_id: order.id,
      provider: params.provider,
      return_url: `${window.location.origin}${trackHref}`,
    },
  });
  return { orderId: order.id, intentUrl: intent.intent_url, trackHref };
}
