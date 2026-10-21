import type { OrderOut } from "@/lib/orders-types";

/**
 * The GA4 `purchase` event for the data layer, read by the GTM container
 * (Google Ads conversion, GA4) and by Metrika (`ecommerce:"dataLayer"`, which
 * accepts the GA4 shape).
 *
 * Sent from the order page once the order is paid — the buyer lands there after
 * the acquirer, and the page already polls the status. Carries the order id, the
 * charged amount and the lines; never the email or a delivery target.
 */

/** A paid order older than this is a revisit, not a conversion. */
const FRESH_MS = 24 * 60 * 60 * 1000;

const sentKey = (orderId: string) => `yp_purchase_sent:${orderId}`;

interface PurchaseItem {
  item_id: string;
  item_name: string;
  item_brand: string;
  price: number;
  quantity: number;
}

export interface PurchaseEvent {
  event: "purchase";
  ecommerce: {
    transaction_id: string;
    value: number;
    currency: string;
    items: PurchaseItem[];
  };
}

/** The event for `order`, or `null` when it is not a fresh paid sale. */
export function purchaseEventFor(order: OrderOut, nowMs: number): PurchaseEvent | null {
  if (order.purpose === "wallet_topup" || order.paid_at === null) return null;
  if (nowMs - Date.parse(order.paid_at) > FRESH_MS) return null;
  const value = Number(order.total_charged);
  if (!Number.isFinite(value) || value <= 0) return null;
  const totalUsd = Number(order.total_usd);
  // Line prices are in USD; spread the charged total over them so the items add
  // up to `value` in the order's own currency.
  const rate = totalUsd > 0 ? value / totalUsd : 0;
  return {
    event: "purchase",
    ecommerce: {
      transaction_id: order.id,
      value,
      currency: order.currency,
      items: order.items.map((item) => ({
        item_id: item.display?.sku_code ?? item.sku_id,
        item_name: item.display?.product_name ?? "",
        item_brand: item.display?.brand_slug ?? "",
        price: Math.round(Number(item.unit_price_usd) * rate * 100) / 100,
        quantity: item.qty,
      })),
    },
  };
}

/**
 * Push the purchase for `order` once per browser. Storage failing (private
 * mode) falls back to sending: a duplicate is deduplicated by `transaction_id`
 * on Google's side, a missed conversion is not recoverable.
 */
export function sendPurchaseOnce(order: OrderOut, nowMs: number = Date.now()): boolean {
  const event = purchaseEventFor(order, nowMs);
  if (event === null) return false;
  try {
    if (window.localStorage.getItem(sentKey(order.id)) !== null) return false;
    window.localStorage.setItem(sentKey(order.id), "1");
  } catch {
    // storage unavailable — send anyway
  }
  window.dataLayer = window.dataLayer ?? [];
  // GA4 asks to clear the previous ecommerce object before a new one.
  window.dataLayer.push({ ecommerce: null });
  window.dataLayer.push(event);
  return true;
}

declare global {
  interface Window {
    dataLayer?: unknown[];
  }
}
