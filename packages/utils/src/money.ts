/** ISO 4217 currencies YuPay handles that carry no minor unit. */
const ZERO_DECIMAL_CURRENCIES = new Set(["UZS"]);

/**
 * Localized word for a UZS amount, mirroring `apps/web/src/lib/seo.ts::uzsWord`
 * and `apps/miniapp/src/lib/currency.ts`'s private helper of the same name —
 * keep all three in sync. Accepts either a bare language tag ("ru") or a
 * region-qualified one ("ru-RU"); callers pass both (next-intl's `useLocale()`
 * yields the bare form, this file's own default param the qualified one).
 */
function uzsWord(locale: string): string {
  const lang = locale.slice(0, 2).toLowerCase();
  if (lang === "ru") return "сум";
  if (lang === "uz") return "soʻm";
  return "UZS";
}

/**
 * Format an amount-string (in major units, e.g. "12.34") plus an ISO 4217 currency
 * (or our crypto pseudocurrency "USDT") for display in the given locale.
 *
 * Amounts always travel as strings to preserve decimal precision; we accept a string here
 * to discourage Number arithmetic at the call site.
 *
 * - USD / RUB and other 2-dp ISO currencies → locale currency style, 2 dp.
 * - UZS → zero decimals with grouping, suffixed with the localized word
 *   (see `uzsWord`) rather than `Intl`'s bare ISO code — the order-confirmation
 *   and order-history screens are the biggest consumers of this formatter
 *   (2026-09-04 review, task C1b).
 * - USDT is not a real ISO 4217 code, so Intl currency style throws; render
 *   it as a plain grouped number with the "USDT" ticker appended.
 */
export function formatMoney(amount: string, currency: string, locale = "ru-RU"): string {
  const num = Number.parseFloat(amount);
  const safe = Number.isFinite(num) ? num : 0;
  const fractionDigits = ZERO_DECIMAL_CURRENCIES.has(currency) ? 0 : 2;

  if (currency === "UZS") {
    // Same defect, same fix as `formatUzs`/`currency.ts::formatMoney`:
    // `Intl`'s `style:"currency"` prints the bare ISO code instead of the
    // word every other soum price in the storefront uses. Build the number
    // ourselves and append the localized word.
    const number = new Intl.NumberFormat(locale, {
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(safe);
    return `${number} ${uzsWord(locale)}`;
  }

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
