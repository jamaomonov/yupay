/**
 * Checkout rules that do not touch the network: who may pay, what the order body is, where the
 * acquirer sends the buyer back. Plain TS, unit-tested.
 */
import type { SkuOut } from "@yupay/api-client/types";

import { skuKind } from "./amount";
import type { PlayerCheckResult } from "./api";

export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function isEmail(value: string): boolean {
  return EMAIL_RE.test(value.trim());
}

/** The acquirers the app offers, in the web storefront's order (Payme converts best). */
export const PAY_METHODS = ["payme", "click", "uzum"] as const;
export type PayMethod = (typeof PAY_METHODS)[number];

/**
 * A SKU bought as one tile. A typed amount (Steam) or a typed quantity (Telegram Stars) has
 * its own field (`lib/amount.ts`).
 */
export function isFixedSku(sku: SkuOut): boolean {
  return skuKind(sku) === "fixed";
}

/**
 * Whether a player check stands in the way of paying. Not pressed, or answered «not found»,
 * blocks; a check that could not run does not, the same rule as the web storefront.
 */
export function checkBlocks(result: PlayerCheckResult | null): boolean {
  return result === null || result.status === "invalid";
}

/** One line as the signed-in account; receipts go where the account says. */
export interface OrderLine {
  skuId: string;
  fields: Record<string, string>;
  /** Stars typed as a count; 1 for everything else. */
  qty?: number;
  /** Steam: the typed dollars, two decimals. */
  amountUsd?: string;
}

/** `POST /orders`: one line, priced in soʻm. */
export function orderBody(line: OrderLine) {
  const fields = Object.fromEntries(
    Object.entries(line.fields).map(([key, value]) => [key, value.trim()]),
  );
  return {
    currency: "UZS",
    items: [
      {
        sku_id: line.skuId,
        qty: line.qty ?? 1,
        ...(line.amountUsd !== undefined ? { amount_usd: line.amountUsd } : {}),
        fulfillment_data: fields,
      },
    ],
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
export function returnUrl(webUrl: string, locale: string, orderId: string): string {
  const prefix = locale === "ru" ? "" : `/${locale}`;
  return `${webUrl.replace(/\/$/, "")}${prefix}/orders/${orderId}`;
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

export type StageTone = "ok" | "warn" | "danger" | "mute";

/** The colour a stage reads in: done is green, waiting amber, failed red, closed grey. */
export function stageTone(stage: OrderStage): StageTone {
  switch (stage) {
    case "done":
      return "ok";
    case "awaiting":
    case "working":
      return "warn";
    case "failed":
      return "danger";
    case "closed":
    case "refunded":
      return "mute";
  }
}

/** Stages that can still change by themselves: the order screen keeps asking. */
export function isLive(stage: OrderStage): boolean {
  return stage === "awaiting" || stage === "working";
}
