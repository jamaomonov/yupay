/**
 * Grouping for the money field, so a customer reads the amount instead of
 * counting zeros.
 *
 * `100000` and `1000000` differ by one character and by a factor of ten — at a
 * glance, in a bold 24px field, they are the same shape. The quick-amount chips
 * below the field were already grouped, which made the field the only place on
 * the page showing a raw run of digits.
 *
 * The stored value stays a plain digit string: grouping is a display concern,
 * and the API wants a number.
 */

/** Strip everything that is not a digit. Soum has no minor unit, so a decimal
 *  separator is not a rounding question — the server refuses 10 000.5 outright. */
export function toDigits(raw: string): string {
  return raw.replace(/\D/g, "");
}

/**
 * Group a digit string for display: `"100000"` → `"100 000"`.
 *
 * Leading zeros are dropped — `"007"` is `7` — because they survive a paste and
 * make the field disagree with the number it will send. An empty string stays
 * empty rather than becoming `0`, so the placeholder still shows.
 */
export function groupDigits(digits: string, locale: string): string {
  const cleaned = toDigits(digits).replace(/^0+(?=\d)/, "");
  if (cleaned === "") return "";
  const intlLocale = locale === "ru" ? "ru-RU" : locale === "uz" ? "uz-UZ" : "en-US";
  // `Number` is exact well past the 5 000 000 ceiling this field allows.
  return new Intl.NumberFormat(intlLocale, { maximumFractionDigits: 0 }).format(Number(cleaned));
}

/** The numeric value a grouped or raw field currently holds. */
export function amountValue(raw: string): number {
  const digits = toDigits(raw);
  return digits === "" ? 0 : Number(digits);
}
