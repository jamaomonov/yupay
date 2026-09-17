/**
 * JSON-LD builders for the reseller site. Small, pure functions returning
 * plain objects — rendering is `<JsonLd data={…}>` (`components/JsonLd.tsx`),
 * which serialises them. `faqPage`, `breadcrumbs` and `techArticle` are the
 * three a later task reuses on `/telegram`, `/api`, `/faq`; the rest exist
 * because the landing needs them today.
 */

/**
 * The single Organization node every JSON-LD block on this site points back
 * to via `@id` — the storefront's own Organization record
 * (`apps/web/src/app/[locale]/layout.tsx`), not a second, competing one.
 * reseller.yupay.uz is a B2B surface of the same business, and search
 * engines should learn that, not learn a duplicate entity.
 */
export const ORGANIZATION_ID = "https://yupay.uz/#organization";

/** The storefront's own Organization, referenced by `@id` rather than
 *  redeclared — this is the one place the reseller site asserts who it is. */
export function organization(): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    "@id": ORGANIZATION_ID,
    name: "YuPay",
    url: "https://yupay.uz",
    sameAs: ["https://reseller.yupay.uz", "https://partners.yupay.uz"],
  };
}

/** This site as a WebSite node, so search engines can attach a sitelinks box. */
export function website(site: string): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    url: site,
  };
}

/** The wholesale program itself, as a Service offered by the Organization. */
export function service(site: string): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "Service",
    name: "YuPay Оптом",
    serviceType: "Wholesale digital goods supply",
    areaServed: ["UZ", "RU", "KZ"],
    provider: { "@id": ORGANIZATION_ID },
    url: site,
  };
}

export interface FaqEntry {
  q: string;
  a: string;
}

/** A page's visible Q&A, as FAQPage — same shape Google expects for the FAQ
 *  rich result. Pass exactly the questions rendered on the page: structured
 *  data that does not match what a visitor sees is against Google's own
 *  guidelines and risks the rich result being pulled entirely. */
export function faqPage(entries: FaqEntry[]): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: entries.map(({ q, a }) => ({
      "@type": "Question",
      name: q,
      acceptedAnswer: { "@type": "Answer", text: a },
    })),
  };
}

export interface BreadcrumbItem {
  name: string;
  url: string;
}

/** A page's position in the site, as BreadcrumbList. 1-indexed, per spec. */
export function breadcrumbs(items: BreadcrumbItem[]): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: item.name,
      item: item.url,
    })),
  };
}

export interface TechArticleParams {
  headline: string;
  description?: string;
  url: string;
  /** ISO 8601. The build's own timestamp — there is no per-page content
   *  timestamp to draw from, same limitation the sitemap's `lastModified` has. */
  dateModified: string;
}

/** A reference/guide page, as TechArticle — the schema.org type built for
 *  developer documentation, distinct from a marketing page's WebPage. */
export function techArticle(params: TechArticleParams): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: params.headline,
    ...(params.description !== undefined ? { description: params.description } : {}),
    url: params.url,
    dateModified: params.dateModified,
  };
}
