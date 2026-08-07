import { expect, test } from "@playwright/test";

/**
 * Both assertions here were written against the bootstrap scaffold: a heading
 * literally reading "YuPay" and a /ping page echoing the API modules. The
 * storefront redesign (150f4ac) replaced the heading and deleted /ping, and
 * nothing updated these — the suite has been red ever since, unnoticed because
 * e2e does not run in CI. Rewritten against what the app actually ships.
 */

test("home page renders the storefront shell", async ({ page }) => {
  await page.goto("/");
  // The header wordmark links home on every page — a stable identity anchor
  // that does not move with marketing copy.
  await expect(page.getByRole("link", { name: "yupay" }).first()).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});

test("catalog lists brands from the API", async ({ page }) => {
  // End-to-end in the sense that matters: the page is server-rendered from a
  // live catalog call, so a brand link proves web → API → DB is intact.
  await page.goto("/store");
  await expect(page.locator('a[href*="/store/"]').first()).toBeVisible();
  expect(await page.locator('a[href*="/store/"]').count()).toBeGreaterThan(0);
});
