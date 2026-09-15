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

/** Day and minute: enough to line a charge up against a support chat. */
export function formatMoment(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}
