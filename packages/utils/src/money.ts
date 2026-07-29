/** ISO 4217 currencies YuPay handles that carry no minor unit. */
const ZERO_DECIMAL_CURRENCIES = new Set(["UZS"]);

/**
 * Format an amount-string (in major units, e.g. "12.34") plus an ISO 4217 currency
 * (or our crypto pseudocurrency "USDT") for display in the given locale.
 *
 * Amounts always travel as strings to preserve decimal precision; we accept a string here
 * to discourage Number arithmetic at the call site.
 *
 * - USD / RUB and other 2-dp ISO currencies → locale currency style, 2 dp.
 * - UZS → zero decimals with grouping.
 * - USDT is not a real ISO 4217 code, so Intl currency style throws; render
 *   it as a plain grouped number with the "USDT" ticker appended.
 */
export function formatMoney(amount: string, currency: string, locale = "ru-RU"): string {
  const num = Number.parseFloat(amount);
  const safe = Number.isFinite(num) ? num : 0;
  const fractionDigits = ZERO_DECIMAL_CURRENCIES.has(currency) ? 0 : 2;

  if (currency === "USDT") {
    const n = safe.toLocaleString(locale, {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    });
    return `${n} USDT`;
  }

  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(safe);
  } catch {
    return `${safe.toFixed(fractionDigits)} ${currency}`;
  }
}
