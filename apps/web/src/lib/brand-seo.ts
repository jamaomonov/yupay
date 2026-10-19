import type { Review } from "./reviews";

/** The site name every brand page title ends with, as the templates write it. */
const SUFFIX = " | YuPay";

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

/**
 * The denomination a brand page answers «how much is it in soʻm» for — the
 * one people search by. Search Console, 3 months to 2026-10-19: «сколько стоит
 * 1000 робуксов в сумах» at position 4.3 with no clicks, plus «1 робукс в
 * сумах» and «робуксы в сумах». The answer is the live price, never copy.
 */
// The answer says a code arrives after payment: voucher brands only, until it is varied.
const PRICE_FAQ_DENOMINATION: Record<string, string> = {
  roblox: "1000 Robux",
};

/** A priced, in-stock row of the brand page — what `priceFaqRow` picks from. */
export interface PricedRow {
  denomination: string | null;
  price: number;
  inStock: boolean;
}

/** The row the price question is about, or `null` when this brand has none or it is sold out. */
export function priceFaqRow<T extends PricedRow>(brandSlug: string, rows: readonly T[]): T | null {
  const wanted = PRICE_FAQ_DENOMINATION[brandSlug];
  if (!wanted) return null;
  return rows.find((r) => r.denomination === wanted && r.inStock && r.price > 0) ?? null;
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
