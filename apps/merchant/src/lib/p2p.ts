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
  if (!rate || !(amountUzs > 0)) return null;
  const r = Number(rate);
  if (!(r > 0)) return null;
  const cents = Math.floor((amountUzs * 100) / r);
  return `${String(Math.floor(cents / 100))}.${String(cents % 100).padStart(2, "0")}`;
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
