import type { Review } from "./reviews";

/** The site name every brand page title ends with, as the templates write it. */
const SUFFIX = " | yupay";

/**
 * A brand page's `<title>`: the brand's own search title for this locale when an
 * admin set one (`seo_title`, e.g. «Алмазы Mobile Legends (MLBB) — купить…»),
 * else the template. The API never sends another locale's copy.
 */
export function brandPageTitle(seoTitle: string | null | undefined, template: string): string {
  const own = seoTitle?.trim();
  return own ? own + SUFFIX : template;
}

/** A brand page's meta description: its own search copy first, then the fallback chain. */
export function brandPageDescription(
  seoDescription: string | null | undefined,
  fallback: string,
): string {
  const own = seoDescription?.trim();
  return own ? own : fallback;
}

/** How many reviews a brand page marks up — enough for a snippet, not a dump. */
const LD_REVIEWS = 5;

export interface ReviewLd {
  "@type": "Review";
  author: { "@type": "Person"; name: string };
  reviewRating: { "@type": "Rating"; ratingValue: number; bestRating: 5 };
  reviewBody: string;
  datePublished: string;
}

/**
 * schema.org `Review` entries for a brand's Product: published reviews that say
 * something (a star-only review has no body Google could show), newest first as
 * the API sends them. A guest review has no name, so it gets the same label the
 * page shows (`anonymous`) — the markup must match what a visitor sees.
 */
export function brandReviewsLd(items: readonly Review[], anonymous: string): ReviewLd[] {
  return items
    .filter((r) => r.body?.trim())
    .slice(0, LD_REVIEWS)
    .map((r) => ({
      "@type": "Review",
      author: { "@type": "Person", name: r.author_name?.trim() || anonymous },
      reviewRating: { "@type": "Rating", ratingValue: r.rating, bestRating: 5 },
      reviewBody: (r.body ?? "").trim(),
      datePublished: r.created_at.slice(0, 10),
    }));
}
