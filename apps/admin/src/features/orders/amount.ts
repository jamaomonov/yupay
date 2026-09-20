import type { OrderAdminOut } from "./types";

/**
 * What an order's money cell should say, and in which currency.
 *
 * A pure function so the column, its sort and the page total cannot disagree
 * about one row — three `? :` chains in JSX is how one of them starts showing
 * a different number from the two beside it.
 *
 * ## Why a merchant order is not just `total_charged`
 *
 * `total_charged` is what the payer was charged **in the order's currency**,
 * and on a retail order that is the whole truth: a 72 813 UZS Elite Pass was
 * paid for with 72 813 so'm.
 *
 * On a merchant order it is the whole truth only for a fixed-price SKU. On a
 * **variable-amount** line it is not, and the gap is deliberate upstream:
 * `merchants/orders.py` writes the line's `unit_price_usd` as the *face value
 * the supplier must load* — $1.00 of Steam credit — because fulfilment reads
 * that field as "how many dollars" (Waxpeer takes it literally). The reseller
 * was charged $1.05. So the order row carries the delivery amount and the
 * deposit ledger carries the price, and the admin list was rendering the
 * first.
 *
 * `deposit_charged_usd` is the ledger's own answer, read off
 * `merchants.deposit.charged_for_orders` — the function whose docstring calls
 * itself the authority on what an order was paid — and batched once per page
 * by `_to_admin_orders_out`, so using it here costs no extra query. It is the
 * same number the merchant's own cabinet, their statement and
 * `/merchant/v1/orders/{id}` already show them, which is the point: an
 * operator explaining a charge must not be reading a different figure from
 * the reseller they are explaining it to.
 *
 * Falls back to `total_charged` when the ledger has no charge. On a merchant
 * order that cannot happen — the charge and the order row are written in one
 * transaction — so the fallback covers a damaged ledger, and showing the face
 * value is better than showing an empty cell.
 */
export function orderAmount(order: OrderAdminOut): { value: string; currency: string } {
  if (order.merchant_id !== null && order.deposit_charged_usd != null) {
    return { value: order.deposit_charged_usd, currency: "USD" };
  }
  return { value: order.total_charged, currency: order.currency };
}

/** The same figure as a number, for sorting and for the page total. */
export function orderAmountValue(order: OrderAdminOut): number {
  return Number.parseFloat(orderAmount(order).value) || 0;
}
