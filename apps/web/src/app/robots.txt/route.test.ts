import { expect, test } from "vitest";

import { GET } from "./route";

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
