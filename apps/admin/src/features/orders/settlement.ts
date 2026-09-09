/**
 * May this order be settled from the order page, and for how much?
 *
 * A pure function so the affordance has one definition and can be falsified:
 * the button, its confirmation, the card's explanatory line and the test that
 * proves a retail order never sees it all read this. The alternative — three
 * `&&` chains in JSX — is how one of them starts disagreeing with the others
 * about a money button.
 *
 * ## What it refuses, and why each refusal is its own answer
 *
 * - **A retail order** (`merchant_id === null`). Its money is at an acquirer
 *   and is reversed through the payments card beside it; crediting a deposit
 *   would move somebody else's money. `merchant_id` is also the URL of the
 *   endpoint, so a retail order could not reach it in any case — but the check
 *   is written and tested rather than left to TypeScript, because "it happens
 *   to be unreachable" is not a rule anyone can see.
 * - **An order with no deposit charge** (`null`, not `0`). There is nothing to
 *   return. On a merchant order this cannot happen — the charge and the order
 *   row are written in one transaction — so it means a hand-edited or damaged
 *   ledger, which is precisely when guessing an amount must not happen.
 * - **An order money has already come back on**, in whole or in part. Square is
 *   obvious. A **partial** is refused too, and that is the interesting one: the
 *   button posts what the order was *charged*, so on a partly settled order it
 *   would be refused by `order_already_settled` every time. Finishing a partial
 *   is a deliberate second decision with its own amount, and it belongs on the
 *   merchant's page where an operator types one — the runbook says so. So this
 *   button can never *produce* a partial and never *completes* one; the card
 *   says which of the two an operator is looking at.
 * - **An order whose delivery has not terminally failed.** This one is
 *   narrower than the plan asked for ("appears only on an unsettled merchant
 *   order") and the narrowing is deliberate, because settling a **live** order
 *   returns the money without stopping the supplier call: nothing cancels the
 *   task, the drain keeps it, and a success then writes a delivery the reseller
 *   can read (`_try_settle_order` declines to advance a closed order, but the
 *   artifact is there). Goods and money — the loophole
 *   `_refuse_a_settled_merchant_order` closes for Retry and manual delivery,
 *   which nothing closes for a settlement. The gap is the API's and predates
 *   this button (the merchant page's form has always allowed it); a one-click
 *   affordance for it on every in-flight B2B order is not something to add
 *   while it is open. So the button waits for a **terminal** state:
 *   `fulfillment_failed` (the case it exists for) or `order_failed` (support
 *   closed it and money may still be owed). `null` is an order in flight and
 *   `fulfillment_delayed` is one still coming — both keep it hidden.
 *
 * ## The amount
 *
 * Exactly what the ledger says the order charged, trimmed to the wire's two
 * decimals. No arithmetic: `deposit_charged_usd` is `NUMERIC(20, 6)` on the
 * wire (`"1.070000"`) and the endpoint's schema is `decimal_places=2`, so the
 * only transformation is dropping trailing zeros. A charge is always a whole
 * cent — `merchants.orders.place` charges a price built to two decimals — and
 * if one ever is not, this returns `null` rather than rounding somebody's
 * money.
 */

import type { OrderAdminOut } from "./types";

/** What the settle button would do, or `null` when it must not be offered. */
export interface MerchantSettlement {
  merchantId: string;
  /** The order's own id — our `orders.id`, which is what the endpoint takes. */
  orderId: string;
  /** Canonical two-decimal USD string, ready for the wire. */
  amount: string;
}

/** Why the button is absent, for the sentence shown in its place.
 *
 *  There is no arm for "retail": `settlementBlock` answers `null` there, and a
 *  variant with no sentence behind it would be a label waiting to render
 *  `undefined` on the one page that must not talk about deposits. */
export type SettlementBlock = "no_charge" | "partly_settled" | "settled" | "still_open";

/** `failure_reason` values that mean the delivery has stopped for good.
 *
 *  The settle button waits for one of these — see the module docstring for why
 *  an order still in flight (or merely delayed) must not be settled with one
 *  click. `order_failed` is here because support closing an order by hand
 *  leaves money owed and settling it afterwards is exactly the procedure. */
const TERMINALLY_STOPPED = new Set(["fulfillment_failed", "order_failed"]);

/**
 * `"1.070000"` → `"1.07"`, or `null` when the value carries a fraction of a
 * cent. String operations only — a ledger amount never goes through a float.
 */
export function toWireAmount(raw: string): string | null {
  const [intRaw = "", fracRaw = ""] = raw.trim().split(".");
  if (!/^\d+$/.test(intRaw)) return null;
  const frac = fracRaw.replace(/0+$/, "");
  if (frac.length > 2 || !/^\d*$/.test(frac)) return null;
  const cents = frac.padEnd(2, "0");
  if (!/[1-9]/.test(intRaw + cents)) return null; // nothing to credit
  return `${intRaw.replace(/^0+(?=\d)/, "")}.${cents}`;
}

/** The settlement this order allows, or `null`. See the module docstring. */
export function merchantSettlement(order: OrderAdminOut): MerchantSettlement | null {
  if (order.merchant_id === null) return null;
  if (order.deposit_charged_usd === null) return null;
  if (Number.parseFloat(order.deposit_returned_usd) !== 0) return null;
  if (order.failure_reason === null || !TERMINALLY_STOPPED.has(order.failure_reason)) return null;
  const amount = toWireAmount(order.deposit_charged_usd);
  if (amount === null) return null;
  return { merchantId: order.merchant_id, orderId: order.id, amount };
}

/**
 * Why there is no button, for a merchant order that has a charge.
 *
 * `null` for an order that can be settled, and for one where saying anything
 * would be noise — a retail order has a payments card two inches away and no
 * business being told about deposits.
 */
export function settlementBlock(order: OrderAdminOut): SettlementBlock | null {
  if (order.merchant_id === null) return null;
  if (order.deposit_charged_usd === null) return "no_charge";
  const returned = Number.parseFloat(order.deposit_returned_usd);
  if (returned === 0) {
    return order.failure_reason !== null && TERMINALLY_STOPPED.has(order.failure_reason)
      ? null
      : "still_open";
  }
  // Compared as numbers deliberately: this picks a **sentence**, not an amount.
  // The exact comparison that decides money is the server's, against the
  // ledger (`order_already_settled`), and it is the one that must not be
  // approximated.
  return returned >= Number.parseFloat(order.deposit_charged_usd) ? "settled" : "partly_settled";
}
