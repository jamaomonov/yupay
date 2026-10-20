/**
 * Dates for the order list, the statement and the key list.
 *
 * Rendered in the **viewer's own** timezone rather than the profile's.
 * `timezone` on a merchant user decides when we mail them; a statement line
 * that disagreed with the clock on the operator's wall while they reconcile it
 * against their books would be the worse surprise. Everything is ISO 8601 UTC
 * in transit either way, so nothing here is the source of truth — only its
 * presentation.
 */

function dayIndex(date: Date): number {
  return Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86_400_000);
}

/**
 * Day and minute: enough to line a charge up against a support chat.
 *
 * Read the way a list is scanned: «Сегодня, 14:27», «Вчера, 09:10», «18 окт., 14:27», and
 * the year only when it is not this one. The full «20 окт. 2026 г., 14:27» on every row of
 * a list that is mostly today was noise. `now` is for tests.
 */
export function formatMoment(iso: string, locale: string, now: Date = new Date()): string {
  const date = new Date(iso);
  const time = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(date);
  const ago = dayIndex(now) - dayIndex(date);
  if (ago === 0 || ago === 1) {
    const word = new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(-ago, "day");
    return `${word.charAt(0).toUpperCase()}${word.slice(1)}, ${time}`;
  }
  const day = new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  }).format(date);
  return `${day}, ${time}`;
}
