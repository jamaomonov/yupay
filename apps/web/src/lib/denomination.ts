const NBSP = " ";

/**
 * A package name as a tile shows it. The name itself is the catalogue's; this
 * only stops it breaking badly:
 *
 * - nothing inside parentheses breaks, so «86 Diamonds (78 + 8)» never wraps as
 *   «(78 +» / «8)» — the line may still break before the bracket;
 * - numbers of five digits and more get their thousands grouped («10000 Robux»
 *   → «10 000 Robux»), the way every price on the page already is. Four-digit
 *   ones stay as written, which is the Russian norm.
 */
export function displayDenomination(name: string): string {
  return name
    .replace(/\d{5,}/g, (n) => n.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP))
    .replace(/\([^)]*\)/g, (group) => group.replace(/ /g, NBSP));
}
