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
