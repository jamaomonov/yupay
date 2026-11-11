/**
 * The public offer (`docs/legal/merchant-offer.ru.md`) as renderable blocks.
 *
 * Not a markdown parser: the document uses headings, paragraphs and bold, and
 * nothing else. A dependency and an XSS surface for that is a bad trade, and
 * the source is ours, not a user's. React escapes every string the page
 * renders from this.
 */

/** The revision line of the document — «**Редакция от 11.11.2026**». */
const REVISION = /^\*\*Редакция от (.+?)\*\*$/m;

/** One block of the document: a section heading or a paragraph. */
export interface OfferBlock {
  heading: boolean;
  text: string;
}

export function parseOffer(raw: string): { revision: string; blocks: OfferBlock[] } {
  const revision = REVISION.exec(raw)?.[1];
  // A missing revision is a broken document, not a degraded one: the page
  // would show a contract without saying which edition it is.
  if (revision === undefined) throw new Error("merchant offer: no «Редакция от …» line");
  const blocks = raw
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(REVISION, "")
    .split(/\n\s*\n/)
    .map((chunk) => chunk.replace(/\s*\n\s*/g, " ").trim())
    // The document's own H1 — the page renders its title above.
    .filter((chunk) => chunk !== "" && !/^#\s/.test(chunk))
    .map((chunk) => ({
      heading: /^#{2,6}\s/.test(chunk),
      text: chunk.replace(/^#{1,6}\s+/, "").replace(/\*\*(.+?)\*\*/g, "$1"),
    }));
  return { revision, blocks };
}
