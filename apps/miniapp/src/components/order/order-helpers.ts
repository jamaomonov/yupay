/**
 * Pure, non-JSX helpers shared by the `OrderSuccess.tsx` page and its
 * extracted `components/order/*` render pieces — order-status constants,
 * the customer-safe artifact-display picker, and the payment-provider
 * label/icon lookups.
 *
 * Extracted out of `OrderSuccess.tsx` (2026-09-03 review) purely to keep
 * that file near the repo's TS file-length budget — no behaviour change.
 * `isGiftDelivery`, `pickArtifactDisplay`, `providerLabel` and
 * `providerIcon` are re-exported from `OrderSuccess.tsx` so existing test
 * imports (`./OrderSuccess`) keep working unchanged.
 */

import type { MessageKey } from "@/lib/i18n";
import type { DeliveryOut, OrderStatus } from "@/lib/orders";

import { translate } from "@/lib/i18n/core";
import { ICON_BY_PROVIDER } from "@/lib/payment-methods";

export const PROCESSING: OrderStatus[] = ["pending_payment", "paid", "fulfilling", "fulfilled"];

export const TERMINAL_FAIL: OrderStatus[] = ["cancelled", "expired", "refunded"];

// Subset of PROCESSING where a delivery is actually being attempted. We hide
// "ожидаем выдачу…" / "пополняем аккаунт…" placeholders outside of these
// states — pending_payment hasn't been paid yet, and expired/cancelled/
// refunded will never fulfil. Showing the spinner there was misleading.
export const AWAITING_DELIVERY: OrderStatus[] = ["paid", "fulfilling", "fulfilled"];

export function isStringRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export const FIELD_LABEL: Record<string, MessageKey> = {
  player_id: "success.field.player_id",
  user_id: "success.field.user_id",
  account_id: "success.field.account_id",
  email: "success.field.email",
  phone: "success.field.phone",
  region: "success.field.region",
  zone_id: "success.field.zone_id",
  character: "success.field.character",
  nickname: "success.field.nickname",
};

export function labelForField(key: string): string {
  const messageKey = FIELD_LABEL[key];
  return messageKey ? translate(messageKey) : key;
}

/** Whether a delivered artifact is a Steam gift, not an ordinary top-up
 *  receipt or a voucher/license code. Exported (pure) for unit testing. */
export function isGiftDelivery(delivery: DeliveryOut | null): boolean {
  return delivery?.artifact.kind === "gift";
}

/** Ordered preference for the artifact's primary copyable identifier — the
 *  first non-empty string value wins. Every key here is part of the API's
 *  customer-facing whitelist (`BUYER_SAFE_ARTIFACT_KEYS` in
 *  `fulfillment/service.py`) — never read `external_id`: no supplier or
 *  admin-manual-completion flow reaching this component ever sets it, and
 *  Phase 1 strips it server-side if one did. */
export const COPYABLE_ARTIFACT_KEYS = [
  "code",
  "key",
  "pin",
  "serial",
  "steam_login",
  "login",
] as const;
export type CopyableArtifactKey = (typeof COPYABLE_ARTIFACT_KEYS)[number];

export const COPYABLE_ARTIFACT_LABEL: Record<CopyableArtifactKey, MessageKey> = {
  code: "success.code",
  key: "success.key",
  pin: "success.pin",
  serial: "success.serial",
  steam_login: "success.steamLogin",
  login: "success.login",
};

export type ArtifactDisplay =
  | { kind: "copyable"; artifactKey: CopyableArtifactKey; value: string }
  | { kind: "text"; value: string }
  | { kind: "fields"; entries: [string, string][] }
  | { kind: "empty" };

/**
 * Decide how to render a non-top-up delivery artifact: a copyable
 * identifier first (code/key/pin/serial/steam_login/login), then a
 * free-text delivery note (message/note — e.g. an admin-manual-completion
 * that hands over an account without a single code/key field), then the
 * customer's own `fulfillment_data` snapshot, and only a bare "credited"
 * line if none of the whitelisted keys carry anything to show. Exported for
 * unit testing — pure, no i18n/React dependency.
 */
export function pickArtifactDisplay(artifact: Record<string, unknown>): ArtifactDisplay {
  for (const key of COPYABLE_ARTIFACT_KEYS) {
    const value = artifact[key];
    if (typeof value === "string" && value.trim().length > 0) {
      return { kind: "copyable", artifactKey: key, value };
    }
  }
  for (const key of ["message", "note"] as const) {
    const value = artifact[key];
    if (typeof value === "string" && value.trim().length > 0) {
      return { kind: "text", value };
    }
  }
  if (isStringRecord(artifact.fulfillment_data)) {
    const entries = Object.entries(artifact.fulfillment_data).filter(
      (entry): entry is [string, string] =>
        typeof entry[1] === "string" && entry[1].trim().length > 0,
    );
    if (entries.length > 0) return { kind: "fields", entries };
  }
  return { kind: "empty" };
}

/**
 * Map a payment-provider slug to the label shown on the order summary.
 * Mirrors ``paymentProviderDisplay`` on web
 * (apps/web/src/lib/payment-providers.ts). Backend already normalizes
 * ``click_miniapp`` → ``click``; we tolerate both. Returns null when there is
 * no provider yet (unpaid order).
 */
export function providerLabel(provider: string | null): string | null {
  switch (provider) {
    case "click":
    case "click_miniapp":
      return "Click";
    case "payme":
      return "Payme";
    case "uzum":
      return "Uzum";
    case "octo":
      return "Octo";
    case "paynet":
      return "Paynet";
    case "wallet":
      return translate("success.paidWithWallet");
    case null:
    case "":
      return null;
    default:
      return provider;
  }
}

/**
 * Small brand mark for the same provider slugs ``providerLabel`` handles.
 * ``null`` for providers with no asset (wallet, Octo, unrecognised slugs) —
 * the label text is all those get.
 */
export function providerIcon(provider: string | null): string | null {
  if (!provider) return null;
  return ICON_BY_PROVIDER[provider] ?? null;
}
