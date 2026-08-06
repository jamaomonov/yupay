/**
 * Parsing for the manual wallet-adjustment amount.
 *
 * This field creates money: a positive value credits the customer, a negative
 * one claws it back. The form used to accept anything non-empty, so `"abc"`,
 * `"1e9"` and `"5,00"` (a comma is the reflex on a Russian keyboard) all went
 * to the server as-is, and a stray `-` silently became a clawback.
 */

export interface ParsedAmount {
  /** Canonical decimal string for the API (dot separator, no spaces). */
  value: string;
  /** True when the operator is taking money away. */
  isDebit: boolean;
  /** Absolute value, for the confirmation copy. */
  absolute: string;
}

export type AmountError = "empty" | "not_a_number" | "zero" | "too_many_decimals" | "too_large";

/** Ledger amounts are NUMERIC(20,6); keep the UI within the same precision. */
const MAX_DECIMALS = 6;
/** Sanity ceiling — a manual adjustment beyond this is a typo, not a decision. */
const MAX_ABS = 1_000_000_000;

/**
 * Parse operator input into a canonical amount, or an error code.
 *
 * Accepts a leading sign, a comma or dot separator, and thousands separators
 * typed as spaces (including the non-breaking space produced by copy-paste from
 * a formatted table). Rejects scientific notation outright — `1e9` is never
 * what someone means to hand a customer.
 */
export function parseAdjustAmount(raw: string): ParsedAmount | AmountError {
  const trimmed = raw.trim();
  if (!trimmed) return "empty";

  // Strip thousands separators (regular + non-breaking + narrow no-break space).
  const normalised = trimmed.replace(/[\s\u00a0\u202f]/g, "").replace(",", ".");

  // Deliberately strict: sign, digits, optional single decimal part. This is
  // what rejects `1e9`, `--5`, `5.5.5` and stray letters.
  const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(normalised);
  if (!match) return "not_a_number";

  const [, sign, whole, decimals = ""] = match;
  if (decimals.length > MAX_DECIMALS) return "too_many_decimals";

  const numeric = Number(`${sign === "-" ? "-" : ""}${whole ?? "0"}.${decimals || "0"}`);
  if (!Number.isFinite(numeric)) return "not_a_number";
  if (numeric === 0) return "zero";
  if (Math.abs(numeric) > MAX_ABS) return "too_large";

  const canonical = `${sign === "-" ? "-" : ""}${whole ?? "0"}${decimals ? `.${decimals}` : ""}`;
  return {
    value: canonical,
    isDebit: sign === "-",
    absolute: `${whole ?? "0"}${decimals ? `.${decimals}` : ""}`,
  };
}

export const AMOUNT_ERROR_TEXT: Record<AmountError, string> = {
  empty: "Введи сумму.",
  not_a_number: "Сумма должна быть числом, например 5000 или -1250.50",
  zero: "Ноль записывать нечего.",
  too_many_decimals: "Не больше 6 знаков после запятой.",
  too_large: "Слишком большая сумма — проверь, не опечатка ли это.",
};
