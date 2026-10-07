/**
 * What a refused `POST /payments/intents` means for the buyer.
 *
 * The API answers a wallet payment the ledger cannot cover with `409` and a
 * detail of the shape `payment provider rejected the request: insufficient
 * wallet balance: have 52821.000000 UZS, need 53667.000000 UZS` — the one
 * refusal the buyer can act on themselves (top up, or pick a card). Until
 * 2026-10-07 the storefront collapsed every intent failure into "couldn't
 * create the order" and created a fresh order on each retry: one customer
 * 846 soʻm short produced 60 unpaid orders in four minutes.
 */
export type IntentFailure =
  | { kind: "insufficient_balance"; have: number | null; need: number | null }
  | { kind: "other" };

const SHORTFALL_RE = /insufficient wallet balance: have ([\d.]+) \w+, need ([\d.]+) \w+/i;

/** Classify a failed intent response from its status and RFC 7807 body. */
export function parseIntentFailure(status: number, body: unknown): IntentFailure {
  const detail =
    body && typeof body === "object" && "detail" in body && typeof body.detail === "string"
      ? body.detail
      : "";
  if (status === 409 && /insufficient wallet balance/i.test(detail)) {
    const m = SHORTFALL_RE.exec(detail);
    const have = m ? Number.parseFloat(m[1] ?? "") : Number.NaN;
    const need = m ? Number.parseFloat(m[2] ?? "") : Number.NaN;
    return {
      kind: "insufficient_balance",
      have: Number.isFinite(have) ? have : null,
      need: Number.isFinite(need) ? need : null,
    };
  }
  return { kind: "other" };
}

/** Thrown by the panel when the intent was refused: the message is already
 *  the buyer's, and the created order stays reusable. */
export class IntentRefused extends Error {}

/** How long a created-but-unpaid order is worth reusing on a retry. The
 *  server expires an order ten minutes after creation; stop one minute early
 *  so a retry never races the expiry sweep. */
export const PENDING_ORDER_REUSE_MS = 9 * 60 * 1000;
