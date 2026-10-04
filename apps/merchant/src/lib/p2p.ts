import type { P2PDeposit } from "./types";

/** Whole seconds until `expiresAt`, never negative. */
export function secondsLeft(expiresAt: string, nowMs: number): number {
  return Math.max(0, Math.floor((Date.parse(expiresAt) - nowMs) / 1000));
}

/** "50 001" in the cabinet's locale — soʻm have no minor unit on screen. */
export function formatSom(amount: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(amount);
}

/**
 * The USD the deposit will get, rounded DOWN to cents — the server's rule, so the
 * preview never promises a cent the credit will not carry. Integer maths on
 * cents keeps floats out of the displayed money.
 */
export function usdPreview(amountUzs: number, rate: string | null): string | null {
  if (!rate || !Number.isSafeInteger(amountUzs) || amountUzs <= 0) return null;
  const match = /^(\d+)(?:\.(\d+))?$/.exec(rate);
  if (match === null) return null;
  const fraction = match[2] ?? "";
  const scaled = BigInt(`${match[1] ?? "0"}${fraction}`);
  if (scaled === 0n) return null;
  // BigInt division floors for positives: ROUND_DOWN, with no float anywhere.
  const cents = (BigInt(amountUzs) * 100n * 10n ** BigInt(fraction.length)) / scaled;
  return `${String(cents / 100n)}.${String(cents % 100n).padStart(2, "0")}`;
}

export type Phase = "amount" | "details" | "paid" | "expired" | "cancelled";

/** Which screen a deposit belongs on. */
export function phase(d: P2PDeposit | null): Phase {
  if (d === null) return "amount";
  switch (d.status) {
    case "pending":
      return "details";
    case "paid":
      return "paid";
    case "expired":
      return "expired";
    case "cancelled":
      return "cancelled";
  }
}

/** The server's quarantine after expiry (`reservations.QUARANTINE`). */
export const QUARANTINE_MS = 10 * 60 * 1000;

/**
 * Until when to keep polling a top-up, in epoch ms, or `null` to stop.
 *
 * An expired reservation still matches a late delivery of an on-time transfer
 * while its amount is quarantined (`expires_at` + 10 min), so the expired
 * screen keeps asking until then and can still flip to "Credited".
 */
export function pollDeadline(d: P2PDeposit | null): number | null {
  if (d === null || (d.status !== "pending" && d.status !== "expired")) return null;
  return Date.parse(d.expires_at) + QUARANTINE_MS;
}

/** The `topUp.*` message key for an API error code, or `null` for "something else". */
export function errorKey(code: string | null): "errNoCard" | "errBusy" | "errRate" | null {
  if (code === "p2p_no_card") return "errNoCard";
  if (code === "p2p_amount_busy") return "errBusy";
  if (code === "fx_unavailable") return "errRate";
  return null;
}

/** `m:ss` for a countdown. */
export function formatClock(seconds: number): string {
  return `${String(Math.floor(seconds / 60))}:${String(seconds % 60).padStart(2, "0")}`;
}

/**
 * Whether a poll response may replace the deposit on screen.
 *
 * A response is stale when a cancel (or "top up again") happened after the
 * request left, or when it belongs to a number that is no longer the current
 * reservation. With no deposit on screen, only a response that raced a cancel
 * is refused: that is how a restored or just-opened top-up gets in.
 */
export function acceptPoll(
  currentNumber: string | null,
  responseNumber: string,
  cancelled: boolean,
): boolean {
  if (cancelled) return false;
  return currentNumber === null || currentNumber === responseNumber;
}
