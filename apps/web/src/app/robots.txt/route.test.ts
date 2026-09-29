import { expect, test, vi } from "vitest";

import { dynamic, GET } from "./route";

test("robots.txt declares content signals and welcomes AI crawlers", async () => {
  const body = await GET().text();
  // Content-Signal: allow search + live AI answers, reserve model training.
  const signals = body.match(/Content-Signal: search=yes, ai-input=yes, ai-train=no/g) ?? [];
  expect(signals.length).toBe(2); // one per group (* and the AI-crawler group)
  expect(body).toContain("User-Agent: GPTBot");
  expect(body).toContain("Sitemap: https://yupay.uz/sitemap.xml");
  expect(body).toContain("Disallow: /admin/");
});

test("keeps crawlers off the token-bearing auth links, in every locale", async () => {
  const body = await GET().text();
  // A bot that renders JS would spend the single-use verify / reset token and
  // leave the real recipient with a dead link — so these must not be fetched
  // at all, not merely left out of the index.
  expect(body).toContain("Disallow: /auth/");
  expect(body).toContain("Disallow: */auth/");
  // Private but handled with `noindex`, which only works while they stay
  // crawlable — blocking them here would strand any indexed URL.
  expect(body).not.toContain("Disallow: /orders/");
  expect(body).not.toContain("Disallow: /account/");
});

test("names the CS2 skins sitemap while skins are on, and only then", async () => {
  vi.stubEnv("SKINS_ENABLED", "true");
  expect(await GET().text()).toContain("Sitemap: https://yupay.uz/skins-sitemap.xml");
  vi.stubEnv("SKINS_ENABLED", "false");
  expect(await GET().text()).not.toContain("skins-sitemap");
  vi.unstubAllEnvs();
});

test("is rendered per request, so the skins flag in the web env is seen", () => {
  expect(dynamic).toBe("force-dynamic");
});
