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
