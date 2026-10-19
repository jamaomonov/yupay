/**
 * Checkout rules that do not touch the network: who may pay, what the order body is, where the
 * acquirer sends the buyer back. Plain TS, unit-tested.
 */
import type { SkuOut } from "@yupay/api-client/types";

import type { PlayerCheckResult } from "./api";

export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function isEmail(value: string): boolean {
  return EMAIL_RE.test(value.trim());
}

/** The acquirers the app offers, in the web storefront's order (Payme converts best). */
export const PAY_METHODS = ["payme", "click", "uzum"] as const;
export type PayMethod = (typeof PAY_METHODS)[number];

/**
 * A SKU bought as one fixed line. A typed amount (Steam) or a typed quantity (Telegram Stars)
 * needs its own input, which the app does not have yet.
 */
export function isFixedSku(sku: SkuOut): boolean {
  if (sku.variable_amount === true) return false;
  return !(sku.amount_unit != null && sku.min_qty != null && sku.max_qty != null);
}

/**
 * Whether a player check stands in the way of paying. Not pressed, or answered «not found»,
 * blocks; a check that could not run does not, the same rule as the web storefront.
 */
export function checkBlocks(result: PlayerCheckResult | null): boolean {
  return result === null || result.status === "invalid";
}

export interface OrderLine {
  skuId: string;
  fields: Record<string, string>;
  email: string;
  /** Signed in: the order is the account's, and the email only says where the receipt goes. */
  signedIn?: boolean;
}

/** `POST /orders`: one fixed line, priced in soʻm. */
export function orderBody(line: OrderLine) {
  const fields = Object.fromEntries(
    Object.entries(line.fields).map(([key, value]) => [key, value.trim()]),
  );
  const email = normaliseEmail(line.email);
  return {
    currency: "UZS",
    items: [{ sku_id: line.skuId, qty: 1, fulfillment_data: fields }],
    // The same split as the website: a guest is identified by the email, an account is not.
    ...(line.signedIn === true
      ? email === ""
        ? {}
        : { delivery_email: email }
      : { guest_email: email }),
  };
}

/**
 * Everything the order is billed from. The caller keeps one `Idempotency-Key` per fingerprint:
 * paying again for the same thing resumes the same order instead of opening a second one.
 */
export function orderFingerprint(line: OrderLine): string {
  return JSON.stringify(orderBody(line));
}

export function normaliseEmail(email: string): string {
  return email.trim().toLowerCase();
}

/**
 * Where the acquirer returns the buyer: the storefront's order page, the one origin the API
 * accepts (`_safe_return_url`). The app does not rely on it — it checks the order itself
 * once the browser closes.
 */
export function returnUrl(
  webUrl: string,
  locale: string,
  orderId: string,
  email: string | null,
): string {
  const prefix = locale === "ru" ? "" : `/${locale}`;
  // A guest's order page needs the email; an account's does not.
  const query = email === null ? "" : `?email=${encodeURIComponent(normaliseEmail(email))}`;
  return `${webUrl.replace(/\/$/, "")}${prefix}/orders/${orderId}${query}`;
}

export type OrderStage = "awaiting" | "working" | "done" | "failed" | "closed" | "refunded";

/** One of six things the buyer needs to know, from the API's ten statuses. */
export function stageOf(status: string): OrderStage {
  switch (status) {
    case "pending_payment":
      return "awaiting";
    case "paid":
    case "fulfilling":
    case "fulfilled":
      return "working";
    case "delivered":
      return "done";
    case "failed":
      return "failed";
    case "refunded":
    case "partially_refunded":
      return "refunded";
    default:
      return "closed";
  }
}

/** Stages that can still change by themselves: the order screen keeps asking. */
export function isLive(stage: OrderStage): boolean {
  return stage === "awaiting" || stage === "working";
}
