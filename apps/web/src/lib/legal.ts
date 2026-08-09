/**
 * The published legal documents, in the order a reader should meet them: the
 * offer that governs a purchase, the agreement that governs use of the service,
 * then privacy, refunds, and who the seller is.
 *
 * One list, because it has three consumers — the index page, the per-document
 * route's `generateStaticParams`, and the sitemap — and they drifted once
 * already: `agreement` shipped in the footer and the router but never reached
 * the sitemap, so the document existed and was never offered to a crawler.
 *
 * Each slug is also an i18n key under `web.legal`, holding `title`, `intro`,
 * `updated` and `sections`.
 */
export const LEGAL_DOCS = ["terms", "agreement", "privacy", "refunds", "imprint"] as const;

export type LegalDoc = (typeof LEGAL_DOCS)[number];

export function isLegalDoc(value: string): value is LegalDoc {
  return (LEGAL_DOCS as readonly string[]).includes(value);
}
