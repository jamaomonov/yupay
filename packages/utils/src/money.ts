/**
 * Format an amount-string (in major units, e.g. "12.34") plus an ISO 4217 currency
 * (or our crypto pseudocurrency "USDT") for display in the given locale.
 *
 * Amounts always travel as strings to preserve decimal precision; we accept a string here
 * to discourage Number arithmetic at the call site.
 */
export function formatMoney(
  amount: string,
  currency: string,
  locale = "ru-RU",
): string {
  const num = Number.parseFloat(amount);
  if (!Number.isFinite(num)) return `${amount} ${currency}`;
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(num);
  } catch {
    return `${num.toFixed(2)} ${currency}`;
  }
}
