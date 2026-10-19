/** Client-side text search for the admin's in-memory lists (brands, products, SKU rows). */

function fold(text: string): string {
  return text.toLowerCase().replaceAll("ё", "е");
}

/**
 * True when every word of `query` appears in one of `fields`, ignoring case (and ё/е).
 * An empty query matches everything; empty fields are skipped.
 */
export function matchesText(
  query: string,
  fields: readonly (string | null | undefined)[],
): boolean {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = fold(fields.filter((f): f is string => Boolean(f)).join(" "));
  return words.every((w) => haystack.includes(w));
}
