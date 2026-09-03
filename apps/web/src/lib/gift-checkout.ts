/**
 * Minimal checkout POST flow for a Steam gift purchase: mint a guest token
 * when needed, `POST /orders`, `POST /payments/intents`, and hand back where
 * the browser should go next.
 *
 * Extracted out of the pattern `PurchasePanel.tsx:1355-1443` establishes
 * (guest token mint, `Idempotency-Key`, `Authorization` Bearer/Guest,
 * `POST /orders` → `POST /payments/intents` → redirect, `saveGuestOrder` for
 * guests) rather than importing that 2 100-line component — a gift line is
 * always exactly one item, one SKU, `qty: 1`, no promo code and no wallet
 * pay (v1 scope cuts — see `GiftPurchasePanel`), so this needs none of its
 * multi-SKU/variable-amount/unit-quantity machinery.
 */
import { getAccessToken, SURFACE } from "./client";
import { mintGuestToken } from "./guest";
import { saveGuestOrder } from "./guest-orders";
import { pathFor } from "./seo";

const API = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export interface GiftFulfillmentData {
  app_id: number;
  package_id: number;
  region: string;
  invite_url: string;
}

export interface BuyGiftParams {
  locale: string;
  skuId: string;
  /** The selected package/zone's quoted sell price. The server re-derives
   *  and bills its own number (`price_gift_line` in `checkout.py`) — this
   *  is only the client's quote, checked server-side within a ±2% band. */
  amountUsd: string;
  fulfillmentData: GiftFulfillmentData;
  /** Delivery address for a signed-in buyer, or the guest's own email. */
  email: string;
  isLoggedIn: boolean;
  provider: string;
  /** The game name, for the guest order-history stub (`saveGuestOrder`). */
  gameName: string;
}

export interface BuyGiftResult {
  orderId: string;
  intentUrl: string | null;
  /** Root-relative order tracking path (carries the guest `?email=` suffix
   *  when applicable) — where to send the browser once payment starts, or
   *  straight away for the dev `mock` provider (which returns a
   *  non-resolvable `intent_url`, same as `PurchasePanel`). */
  trackHref: string;
}

/**
 * Thrown when `POST /orders` answers 422 carrying
 * `extra.expected_amount_usd` — the supplier price moved since the panel
 * last quoted it (see `price_gift_line`'s ±2% tolerance in `checkout.py`).
 * Callers should refresh the game detail and re-render at the server's own
 * figure rather than retry blindly with the same amount.
 */
export class GiftPriceChangedError extends Error {
  constructor(public readonly expectedAmountUsd: string) {
    super("gift price changed");
    this.name = "GiftPriceChangedError";
  }
}

/** Pulls `extra.expected_amount_usd` out of an RFC 7807 problem+json body —
 *  see `app_error_handler` in `core/errors.py`: `body.update(exc.extra)`,
 *  and `price_gift_line` raises with `extra={"expected_amount_usd": ...}`,
 *  so the field lands nested under `extra`, not at the body's top level. */
function extractExpectedAmount(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const extra = (body as Record<string, unknown>).extra;
  if (!extra || typeof extra !== "object") return null;
  const value = (extra as Record<string, unknown>).expected_amount_usd;
  return typeof value === "string" ? value : null;
}

/**
 * Runs the gift checkout POST flow end to end: guest token mint (guests
 * only), `POST /orders`, `POST /payments/intents`, and — for a guest —
 * remembers the order locally via `saveGuestOrder`, the same way
 * `PurchasePanel` does so it shows up in this browser's guest order list.
 *
 * Never redirects itself; the caller decides where to send the browser next
 * (a real acquirer's hosted page via `intentUrl`, or straight to
 * `trackHref` for the dev `mock` provider).
 *
 * @throws GiftPriceChangedError when the server rejects the quoted price.
 */
export async function buyGift(params: BuyGiftParams): Promise<BuyGiftResult> {
  const { locale, skuId, amountUsd, fulfillmentData, email, isLoggedIn, provider, gameName } =
    params;

  let auth: { Authorization: string };
  if (isLoggedIn) {
    const token = getAccessToken();
    if (!token) throw new Error("gift checkout: no access token for a signed-in buyer");
    auth = { Authorization: `Bearer ${token}` };
  } else {
    const access_token = await mintGuestToken(email);
    auth = { Authorization: `Guest ${access_token}` };
  }

  const orderBody = {
    currency: "UZS",
    items: [
      {
        sku_id: skuId,
        qty: 1,
        amount_usd: amountUsd,
        fulfillment_data: fulfillmentData,
      },
    ],
    // `guest_email` is the guest's identity on the order; `delivery_email` is
    // where a signed-in buyer's mail goes — same split `PurchasePanel` sends.
    ...(isLoggedIn ? { delivery_email: email } : { guest_email: email }),
  };

  const orderRes = await fetch(`${API}/api/v1/orders`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept-Language": locale,
      "Idempotency-Key": crypto.randomUUID(),
      "X-Yupay-Surface": SURFACE,
      ...auth,
    },
    body: JSON.stringify(orderBody),
  });

  if (!orderRes.ok) {
    if (orderRes.status === 422) {
      const body: unknown = await orderRes.json().catch(() => null);
      const expected = extractExpectedAmount(body);
      if (expected !== null) throw new GiftPriceChangedError(expected);
    }
    throw new Error(`gift checkout: order creation failed (${String(orderRes.status)})`);
  }
  const order = (await orderRes.json()) as { id: string };

  const emailSuffix = isLoggedIn ? "" : `?email=${encodeURIComponent(email)}`;
  const trackHref = pathFor(locale, `/orders/${order.id}${emailSuffix}`);
  const returnUrl = `${window.location.origin}${trackHref}`;

  // Guest payment intents require the email as a query param — the API
  // rebuilds the guest-token hash from it to verify the Guest bearer (see
  // `payments/routes.py::_resolve_actor`).
  const intentsUrl = isLoggedIn
    ? `${API}/api/v1/payments/intents`
    : `${API}/api/v1/payments/intents?email=${encodeURIComponent(email)}`;

  const intentRes = await fetch(intentsUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID(),
      "X-Yupay-Surface": SURFACE,
      ...auth,
    },
    body: JSON.stringify({ order_id: order.id, provider, return_url: returnUrl }),
  });
  if (!intentRes.ok) throw new Error("gift checkout: payment intent creation failed");
  const intent = (await intentRes.json()) as { intent_url: string | null };

  if (!isLoggedIn) {
    saveGuestOrder({
      orderId: order.id,
      email,
      brandSlug: "steam-gifts",
      brandName: gameName,
      createdAt: new Date().toISOString(),
    });
  }

  return { orderId: order.id, intentUrl: intent.intent_url, trackHref };
}
