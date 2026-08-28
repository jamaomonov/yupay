/**
 * The one money formatter.
 *
 * Every figure a partner sees on this site is money. A panel that renders it
 * three different ways looks broken even when the numbers are right, so
 * nothing formats an amount inline.
 *
 * UZS has no subunit in practice — tiyin coins are defunct and the catalog
 * prices to whole so'm — so fractions are never shown. The API returns money
 * as decimal strings; both shapes are accepted here so a caller never has to
 * decide whether to parse first.
 */

const ZERO_DECIMAL = new Set(["UZS"]);

export function formatMoney(value: number | string, currency = "UZS", locale = "ru-RU"): string {
  const n = typeof value === "string" ? Number.parseFloat(value) : value;
  const safe = Number.isFinite(n) ? n : 0;
  const digits = ZERO_DECIMAL.has(currency) ? 0 : 2;
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(safe);
  } catch {
    // An unknown currency code must not blank a balance out.
    return `${safe.toLocaleString(locale, { maximumFractionDigits: digits })} ${currency}`;
  }
}

/** Shorthand for the currency every partner is actually paid in. */
export function formatUzs(value: number | string): string {
  return formatMoney(value, "UZS");
}
