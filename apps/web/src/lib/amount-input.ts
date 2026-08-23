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

/**
 * Keystroke handling: keep the digits, drop everything else.
 *
 * Deliberately does not try to read a fraction. It cannot: in `en` the field's
 * own group separator is a comma, so `250,000` minus one character is
 * `250,00` — indistinguishable, by string alone, from two-hundred-fifty point
 * zero zero. A version of this that guessed turned one Backspace into a
 * thousandfold cut, silently, on a money field. Paste is where a fraction
 * actually arrives, and paste is where it is handled — see `pastedDigits`.
 */
export function toDigits(raw: string): string {
  return raw.replace(/\D/g, "");
}

/**
 * Paste handling: drop a trailing fraction, keep the grouping.
 *
 * `"50000.00"` is what an invoice or a bank statement puts on the clipboard —
 * most software shows two decimals whether or not the currency has them. Read
 * as digits it becomes `5000000`: a hundredfold inflation landing exactly on
 * the 5 000 000 ceiling, past every bound and quantum check on both sides,
 * with the field showing the inflated figure as if it had been asked for.
 *
 * Both separators are accepted regardless of locale, because a paste comes
 * from wherever the customer copied it and a Russian customer can perfectly
 * well paste an English-formatted number. Grouping is only ever three digits,
 * so a run of one or two behind a separator is not grouping.
 */
export function pastedDigits(raw: string): string {
  return toDigits(raw.replace(/[.,](\d{1,2})\s*$/, ""));
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

/**
 * Where the caret belongs after regrouping.
 *
 * Rewriting the field's value on every keystroke throws the caret to the end,
 * so correcting a digit in the middle of `1 923 456` was impossible: the next
 * character landed at the far end instead of beside the one being fixed. The
 * separators move as the number grows, so the position cannot be reused —
 * what survives an edit is *how many digits are to the left of it*.
 *
 * @param formatted the grouped string now in the field
 * @param digitsBefore how many digits were left of the caret after the edit
 * @returns the offset just past the `digitsBefore`-th digit
 */
export function caretAfterDigits(formatted: string, digitsBefore: number): number {
  if (digitsBefore <= 0) return 0;
  let seen = 0;
  for (let i = 0; i < formatted.length; i += 1) {
    if (/\d/.test(formatted[i] ?? "")) {
      seen += 1;
      if (seen === digitsBefore) return i + 1;
    }
  }
  return formatted.length;
}

/** How many digits sit left of `caret` in `raw`. */
export function digitsBeforeCaret(raw: string, caret: number): number {
  return toDigits(raw.slice(0, caret)).length;
}
