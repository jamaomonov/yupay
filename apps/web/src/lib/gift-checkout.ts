/**
 * Minimal checkout POST flow for a Steam gift purchase: mint a guest token
 * when needed, `POST /orders`, `POST /payments/intents`, and hand back where
 * the browser should go next.
 *
 * Extracted out of the pattern `PurchasePanel.tsx:1355-1443` establishes
 * (guest token mint, `Idempotency-Key`, `Authorization` Bearer/Guest,
 * `POST /orders` → `POST /payments/intents` → redirect, `saveGuestOrder` for
 * guests) rather than importing that 2 100-line component — a gift line is
 * always exactly one item, one SKU, `qty: 1`, no promo code and no quantity
 * (v1 scope cuts — see `GiftPurchasePanel`), so this needs none of its
 * multi-SKU/variable-amount/unit-quantity machinery. `provider` passes
 * straight through to the intents body, so paying from the wallet balance
 * needs no branch here either — `WalletGateway` settles synchronously and
 * the response comes back with `intent_url: null`, same shape as the dev
 * `mock` provider, which the caller already treats as "done, go to the
 * order page" rather than "redirect to a hosted payment page".
 */
import { ApiError, getAccessToken, SURFACE } from "./client";
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
  /**
   * The `Idempotency-Key` sent with `POST /orders`. Owned by the caller (the
   * panel), not minted here — `create_order` replays by this key
   * (`_existing_idempotent_order` in `orders/service.py`), so a caller keeps
   * it sticky across a failed-payment retry to resume the same order rather
   * than creating a second one, and mints a fresh one when the order
   * contents change, after a success, or when a stale-order retry is
   * needed (see `orderFingerprint` / `isOrderNotAwaitingPaymentConflict`
   * below). The payment *intent*'s own key is still minted per attempt
   * inside this function — retrying an intent for the same order is
   * already "create or reuse" server-side.
   */
  idempotencyKey: string;
}

/**
 * The subset of `BuyGiftParams` that determines the order's contents on
 * `POST /orders` — everything `orderFingerprint` hashes. Deliberately
 * excludes `provider`: switching card ↔ wallet is the same order, not a new
 * one, so it must never change the fingerprint.
 */
export interface OrderFingerprintInput {
  skuId: string;
  amountUsd: string;
  fulfillmentData: GiftFulfillmentData;
  /** Delivery address for a signed-in buyer, or the guest's own email. */
  email: string;
}

/**
 * A pure hash of exactly the fields that determine the order body `buyGift`
 * sends to `POST /orders` — `sku_id`, `qty` (always 1 for a gift line),
 * `amount_usd`, every `fulfillment_data` field, and the delivery email.
 *
 * This is the correctness-by-construction half of the sticky order key: the
 * caller mints a new `Idempotency-Key` exactly when this string changes
 * from the one it last used, rather than resetting it from scattered input
 * handlers (a forgotten one would replay a stale key and charge the buyer
 * for their OLD selection). Over-resetting — treating two fingerprints as
 * different when the order would actually be identical — is safe; it is
 * exactly today's "always mint a new key" behaviour. Under-resetting is a
 * money bug, so every field the server bills from belongs here.
 */
export function orderFingerprint(input: OrderFingerprintInput): string {
  return JSON.stringify({
    sku_id: input.skuId,
    qty: 1,
    amount_usd: input.amountUsd,
    fulfillment_data: {
      app_id: input.fulfillmentData.app_id,
      package_id: input.fulfillmentData.package_id,
      region: input.fulfillmentData.region,
      invite_url: input.fulfillmentData.invite_url,
    },
    email: input.email,
  });
}

/**
 * True when `err` is the 409 `create_intent` raises for an order that has
 * walked past `pending_payment` (most commonly `ORDER_EXPIRY_SECONDS`
 * elapsing and the scheduler flipping it to `expired` before a retry
 * landed) — `ConflictError("order is not awaiting payment", extra=
 * {"status": order.status})` in `payments/service.py`. Matched structurally
 * on the 409 status plus the `extra.status` field that guard's `extra=`
 * keyword puts on the body, never by matching `detail` text, which is not a
 * stable contract and is shared prose with other 409s from the same
 * endpoint (see the `extra.provider` / `extra.current_provider` conflicts
 * right below it).
 */
export function isOrderNotAwaitingPaymentConflict(err: unknown): boolean {
  return err instanceof ApiError && err.status === 409 && typeof err.extra?.status === "string";
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

/** Pulls the RFC 7807 `extra` object out of a parsed problem+json body — see
 *  `app_error_handler` in `core/errors.py`: `body.update(exc.extra)` nests a
 *  raiser's `extra={...}` keyword under this key rather than merging its
 *  fields at the body's top level. `body` is trusted server JSON, not user
 *  input — narrowing its `unknown` shape here is that trade-off's one place,
 *  reused by every caller below instead of repeating the cast. */
function extractExtra(body: unknown): Record<string, unknown> | undefined {
  if (!body || typeof body !== "object") return undefined;
  const extra = (body as Record<string, unknown>).extra;
  return extra && typeof extra === "object" ? (extra as Record<string, unknown>) : undefined;
}

/** Pulls `extra.expected_amount_usd` out of an RFC 7807 problem+json body —
 *  `price_gift_line` raises with `extra={"expected_amount_usd": ...}`. */
function extractExpectedAmount(body: unknown): string | null {
  const value = extractExtra(body)?.expected_amount_usd;
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
  const {
    locale,
    skuId,
    amountUsd,
    fulfillmentData,
    email,
    isLoggedIn,
    provider,
    gameName,
    idempotencyKey,
  } = params;

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
      // Caller-owned, not minted here — see `BuyGiftParams.idempotencyKey`.
      // `create_order` replays by this key, which is the whole mechanism a
      // retry after a failed payment resumes the same order instead of
      // creating a second one.
      "Idempotency-Key": idempotencyKey,
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
  if (!intentRes.ok) {
    // Mirrors what `apiFetch` does internally (this call is a raw `fetch`,
    // not `apiFetch`) so the RFC 7807 `detail` reaches the caller the same
    // way it does everywhere else in the app — `create_intent`'s 409 for a
    // wallet payment ("insufficient wallet balance: have … need …") is
    // written to be shown, not swallowed (see the comment above
    // `ConflictError` in `payments/service.py::create_intent`). `extra` also
    // rides along so `isOrderNotAwaitingPaymentConflict` can tell that
    // specific 409 apart from every other one this endpoint raises.
    let type: string | undefined;
    let detail: string | undefined;
    let extra: Record<string, unknown> | undefined;
    try {
      const body: unknown = await intentRes.json();
      if (body && typeof body === "object") {
        if ("type" in body && typeof body.type === "string") type = body.type;
        if ("detail" in body && typeof body.detail === "string") detail = body.detail;
      }
      extra = extractExtra(body);
    } catch {
      /* non-JSON or empty error body — leave all three undefined */
    }
    throw new ApiError(intentRes.status, "/payments/intents", type, detail, extra);
  }
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
