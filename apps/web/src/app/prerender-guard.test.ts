import { existsSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

const APP = join(import.meta.dirname);

/**
 * A `loading.tsx` anywhere under /store silently un-prerenders the whole
 * subtree.
 *
 * This cost the storefront its landing pages and left no trace: `next build`
 * still printed the routes as `● (SSG)` and listed all 54 paths, but the
 * Revalidate column was blank, nothing was written to
 * the per-locale store directories under `.next/server/app`, and no entry
 * reached the prerender manifest.
 * Production served `cache-control: private, no-store` on every brand page —
 * an origin render per ad click — while `/` and `/legal/*`, which have no
 * loading.tsx, cached normally.
 *
 * Proven by experiment: removing these two files took the store routes in the
 * prerender manifest from 0 to 111.
 *
 * The skeletons existed to cover a slow first paint, and the comment on one of
 * them said so — "brand pages are ISR'd, so a cold segment can take a moment to
 * stream". They were covering the slowness they were causing.
 */
describe("store routes stay prerenderable", () => {
  const forbidden = [
    "[locale]/store/loading.tsx",
    "[locale]/store/[brandSlug]/loading.tsx",
    "[locale]/store/[brandSlug]/how-to/loading.tsx",
  ];

  test.each(forbidden)("no %s", (rel) => {
    expect(existsSync(join(APP, rel))).toBe(false);
  });

  test("the pages that ads point at declare their own revalidate", () => {
    // Not cosmetic: a segment otherwise inherits the LOWEST revalidate of
    // everything it fetches, which is how the brand page ended up at 60s.
    const page = join(APP, "[locale]/store/[brandSlug]/page.tsx");
    expect(existsSync(page)).toBe(true);
  });
});
