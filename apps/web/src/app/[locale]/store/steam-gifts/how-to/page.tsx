import HowToPage, { generateMetadata as brandHowToMetadata } from "../../[brandSlug]/how-to/page";

import type { Metadata } from "next";

/**
 * `/store/steam-gifts/how-to`, which without this file is a 404.
 *
 * Next resolves a static segment ahead of a dynamic one, left to right. At
 * `/store/steam-gifts/…` the literal `steam-gifts` directory therefore beats
 * `[brandSlug]`, and the next segment falls into this route's sibling
 * `[appId]` — so `how-to` was being read as a Steam app id, `Number("how-to")`
 * came back NaN, and the page called `notFound()`.
 *
 * It looked like it worked for a long time because the prerendered HTML
 * outlived the collision: the URL is listed in `sitemap.ts` for every brand,
 * and the cached copy answered 200 until something made it revalidate. Which
 * means the sitemap was advertising a 404 to crawlers, and the brand hub now
 * links to the same URL whenever the brand has `instructions`.
 *
 * A static segment of its own is the fix — it outranks `[appId]` by the same
 * rule that caused the problem. The page itself is the brand how-to with the
 * slug pinned; duplicating that component to change one constant is how the
 * two copies drift.
 */
const BRAND_SLUG = "steam-gifts";

/** Matches the brand how-to it delegates to. */
export const revalidate = 300;

function withSlug(
  params: Promise<{ locale: string }>,
): Promise<{ locale: string; brandSlug: string }> {
  return params.then((p) => ({ ...p, brandSlug: BRAND_SLUG }));
}

export function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  return brandHowToMetadata({ params: withSlug(params) });
}

export default function SteamGiftsHowToPage({ params }: { params: Promise<{ locale: string }> }) {
  return HowToPage({ params: withSlug(params) });
}
