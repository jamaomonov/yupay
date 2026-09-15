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
