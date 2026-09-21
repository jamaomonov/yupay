/**
 * Machine vocabularies rendered as words.
 *
 * Each map is deliberately **explicit and partial**: the API documents these
 * as additive vocabularies, so a value we have never seen must show as itself
 * rather than as a wrong guess or an empty cell. Deriving the key from the
 * code (`fulfillment_failed` → `failureFulfillmentFailed`) would make a new
 * value render as a missing-translation crash instead.
 */

/** `Order.status` → a key under the `merchant.orders` namespace. */
const ORDER_STATUS: Record<string, string> = {
  pending_payment: "statusPendingPayment",
  paid: "statusPaid",
  fulfilling: "statusFulfilling",
  delivered: "statusDelivered",
  failed: "statusFailed",
  cancelled: "statusCancelled",
  refunded: "statusRefunded",
};

/** The seven a merchant can filter by, in the order they happen. */
export const ORDER_FILTERS = [
  "pending_payment",
  "paid",
  "fulfilling",
  "delivered",
  "failed",
  "cancelled",
  "refunded",
] as const;

/** `failure_reason` → a key, for the sentence shown on a closed order. */
const FAILURE_REASON: Record<string, string> = {
  fulfillment_delayed: "failureFulfillmentDelayed",
  fulfillment_failed_refunded: "failureFulfillmentFailedRefunded",
  fulfillment_failed: "failureFulfillmentFailed",
  order_failed: "failureOrderFailed",
};

/** Ledger `kind` → a key under `merchant.transactions`. */
const TRANSACTION_KIND: Record<string, string> = {
  merchant_deposit_credit: "kindDepositCredit",
  // Shipped without this one, so the rarest movement on the ledger — and the
  // only one that takes money off a reseller — rendered as the raw string
  // `merchant_deposit_debit`, by the very rule above that keeps an unknown
  // kind readable. The map is partial on purpose; it still has to be current.
  merchant_deposit_debit: "kindDepositDebit",
  merchant_order_charge: "kindOrderCharge",
  merchant_order_refund: "kindOrderRefund",
};

type Translate = (key: string) => string;

function lookup(map: Record<string, string>, code: string, t: Translate): string {
  const key = map[code];
  return key === undefined ? code : t(key);
}

export function orderStatusLabel(status: string, t: Translate): string {
  return lookup(ORDER_STATUS, status, t);
}

export function failureLabel(reason: string, t: Translate): string {
  return lookup(FAILURE_REASON, reason, t);
}

export function transactionKindLabel(kind: string, t: Translate): string {
  return lookup(TRANSACTION_KIND, kind, t);
}

/**
 * Status → badge tone, shared by every screen that shows an order status.
 *
 * Anything unlisted renders neutral, the same rule the label maps use: a
 * status we have not met should look unremarkable rather than alarming.
 * `text-primary-ink` and not `text-primary` — the accent is a fill colour and
 * fails contrast as ink on the light theme.
 */
const ORDER_TONE: Record<string, string> = {
  delivered: "text-primary-ink bg-primary/10",
  paid: "text-blue bg-blue/10",
  fulfilling: "text-gold bg-gold/10",
  pending_payment: "text-gold bg-gold/10",
  failed: "text-danger bg-danger/10",
  cancelled: "text-tx-mute bg-tx-mute/10",
  refunded: "text-tx-mute bg-tx-mute/10",
};

export function orderStatusTone(status: string): string {
  return ORDER_TONE[status] ?? "text-tx-mute bg-tx-mute/10";
}

/** The human name of an order: brand and package when the API sent them,
 *  the SKU code when it did not, the caller's fallback when even that is
 *  empty. A cabinet order's `merchant_order_id` is `manual-<uuid>` — a key,
 *  not a name — so it never appears as a title. */
export function orderTitle(
  row: { sku_code: string; sku_name?: string | null; brand_name?: string | null },
  fallback: string,
): string {
  const parts = [row.brand_name, row.sku_name].filter((p): p is string => Boolean(p));
  if (parts.length > 0) return parts.join(" · ");
  return row.sku_code || fallback;
}
