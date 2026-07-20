/**
 * Promo redemption error → message key.
 *
 * The endpoint answers RFC 7807 problem+json. A 409 alone is ambiguous — the
 * code may be spent, expired, exhausted or switched off — so the backend tags
 * each refusal with a machine-readable ``code`` (promo/service.py) and we map
 * it to a specific line. Anything unrecognised degrades to the generic wording
 * rather than leaking the English ``detail`` at the customer.
 */

import type { MessageKey } from "@/lib/i18n";

import { ApiError } from "./api";

const CONFLICT_LABEL: Record<string, MessageKey> = {
  already_redeemed: "wallet.promoAlreadyUsed",
  expired: "wallet.promoExpired",
  exhausted: "wallet.promoExhausted",
  inactive: "wallet.promoInactive",
};

/** Read the problem+json ``code`` member, if the body carries one. */
function problemCode(body: unknown): string | null {
  if (body !== null && typeof body === "object" && "code" in body) {
    const raw = (body as { code?: unknown }).code;
    return typeof raw === "string" ? raw : null;
  }
  return null;
}

export function promoErrorKey(err: unknown): MessageKey {
  if (!(err instanceof ApiError)) return "wallet.promoError";
  if (err.status === 404) return "wallet.promoNotFound";
  if (err.status === 409) {
    const code = problemCode(err.body);
    // Older API builds answer 409 without a code — keep the blanket wording.
    return (code !== null ? CONFLICT_LABEL[code] : undefined) ?? "wallet.promoUsed";
  }
  return "wallet.promoError";
}
