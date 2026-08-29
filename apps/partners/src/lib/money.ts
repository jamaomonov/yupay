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
  // The default is a fallback for callers with no locale to hand, not a
  // licence to ignore one. Anything rendering to a partner passes the active
  // locale — an English panel grouping digits the Russian way is exactly what
  // AGENTS.md §11 forbids.
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
export function formatUzs(value: number | string, locale = "ru-RU"): string {
  return formatMoney(value, "UZS", locale);
}

/**
 * A date, in the reader's locale.
 *
 * Here rather than inline in each table: both of them were calling
 * `toLocaleDateString("ru-RU")`, so an English partner read Russian dates
 * beside English column headings.
 */
export function formatDate(iso: string, locale: string): string {
  return new Date(iso).toLocaleDateString(locale, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

/**
 * "10.00" → "10".
 *
 * Rates come off a `Numeric(5,2)` column, and "Скидка 10.00%" reads like a
 * rounding artefact rather than a round number. The storefront's promo field
 * learned this separately; the panel showed the raw value.
 */
export function tidyPercent(raw: string | number): string {
  const n = typeof raw === "string" ? Number.parseFloat(raw) : raw;
  return Number.isFinite(n) ? String(n) : String(raw);
}
