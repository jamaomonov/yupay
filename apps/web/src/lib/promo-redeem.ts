/**
 * Promo redemption error → message key.
 *
 * `POST /promo/redeem` answers RFC 7807 problem+json. A 409 alone is
 * ambiguous — the code may already be redeemed, switched off, expired or
 * exhausted — so the backend tags each refusal with a machine-readable
 * `code` (`promo/service.py`), which `ApiError.code` carries straight from
 * the body's top level (see `client.ts`). Anything unrecognised degrades to
 * the generic wording rather than leaking the English `detail` at the
 * customer.
 *
 * Ported from the Mini App's `lib/promo.ts` — same mapping, same reasoning.
 * Keys here are relative to the `web.wallet` next-intl namespace, the one
 * the wallet page's own `t` is already scoped to.
 */

import { ApiError } from "./client";

export type PromoErrorKey =
  | "promoNotFound"
  | "promoAlreadyUsed"
  | "promoExpired"
  | "promoExhausted"
  | "promoInactive"
  | "promoUsed"
  | "promoError";

const CONFLICT_LABEL: Record<string, PromoErrorKey> = {
  already_redeemed: "promoAlreadyUsed",
  expired: "promoExpired",
  exhausted: "promoExhausted",
  inactive: "promoInactive",
};

export function promoErrorKey(err: unknown): PromoErrorKey {
  if (!(err instanceof ApiError)) return "promoError";
  if (err.status === 404) return "promoNotFound";
  if (err.status === 409) {
    // Older API builds (or a code this frontend doesn't know yet) answer 409
    // with no recognised `code` — keep the blanket wording rather than
    // leaking one.
    return (err.code !== undefined ? CONFLICT_LABEL[err.code] : undefined) ?? "promoUsed";
  }
  return "promoError";
}
