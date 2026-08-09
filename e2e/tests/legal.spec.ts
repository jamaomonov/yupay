import { expect, test } from "@playwright/test";

/**
 * `/legal` is the address that gets handed around — linked from the Mini App
 * profile, pasted into a support reply, given to an acquirer. It answered 404
 * for as long as the documents existed, because every link pointed at a leaf.
 *
 * The list below is deliberately a second copy of `apps/web/src/lib/legal.ts`.
 * An assertion that reads its expectations from the code under test proves
 * nothing; this one fails when a document is added to the app and not to the
 * index — which is exactly how `agreement` came to be missing from the sitemap.
 */
const DOCS = ["terms", "agreement", "privacy", "refunds", "imprint"] as const;

test("the index offers every published document and nothing else", async ({ page }) => {
  await page.goto("/legal");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  const hrefs = await page
    .locator('main a[href*="/legal/"]')
    .evaluateAll((els) => els.map((el) => (el as HTMLAnchorElement).getAttribute("href") ?? ""));
  const slugs = [...new Set(hrefs.map((h) => h.split("/legal/")[1]).filter(Boolean))].sort();
  expect(slugs).toEqual([...DOCS].sort());
});

test("every document the index offers actually resolves", async ({ request }) => {
  for (const doc of DOCS) {
    const res = await request.get(`/legal/${doc}`, { maxRedirects: 0 });
    expect(res.status(), `/legal/${doc} must be served directly`).toBe(200);
  }
});

test("the index is served directly in every locale", async ({ request }) => {
  // No redirect on any of these: `ru` is the default locale and takes no
  // prefix, so a link built for a Russian customer must land, not bounce.
  for (const path of ["/legal", "/en/legal", "/uz/legal"]) {
    const res = await request.get(path, { maxRedirects: 0 });
    expect(res.status(), `${path} must be served directly`).toBe(200);
  }
});

test("a document links back up to the index", async ({ page }) => {
  await page.goto("/legal/agreement");
  // Scoped to `main`: the site footer also links to the index, and matching
  // that would pass even if the breadcrumb lost its middle step.
  await expect(page.locator('main nav a[href="/legal"]')).toHaveCount(1);
});
