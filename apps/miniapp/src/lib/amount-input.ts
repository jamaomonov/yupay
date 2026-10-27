/**
 * The wallet top-up amount field: what is stored vs what is shown.
 *
 * The state keeps the bare number («50000», «12.5») so parsing and the quick
 * chips stay simple; the field shows it grouped by thousands («50 000») —
 * a soʻm amount without spaces was hard to read (owner, 2026-10-27).
 */

/** Non-breaking space: a group never wraps away from its number. */
const GROUP = " ";

/** What the customer typed → the bare number: digits and one «.» (a «,» counts as one). */
export function cleanAmount(typed: string): string {
  const v = typed.replace(/[^\d.,]/g, "").replace(/,/g, ".");
  const dot = v.indexOf(".");
  return dot === -1 ? v : v.slice(0, dot + 1) + v.slice(dot + 1).replace(/\./g, "");
}

/** The bare number → the field's text, thousands grouped: «1234567.5» → «1 234 567.5». */
export function groupAmount(raw: string): string {
  const [whole = "", fraction] = raw.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, GROUP);
  return fraction === undefined ? grouped : `${grouped}.${fraction}`;
}
