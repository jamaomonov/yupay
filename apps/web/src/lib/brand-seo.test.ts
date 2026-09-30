import { expect, it } from "vitest";

import { brandPageDescription, brandPageTitle } from "./brand-seo";

it("uses the brand's own search title when it has one", () => {
  expect(
    brandPageTitle("Алмазы Mobile Legends (MLBB) — купить", "Mobile Legends — пополнение | yupay"),
  ).toBe("Алмазы Mobile Legends (MLBB) — купить | yupay");
});

it("falls back to the template when the title is missing or blank", () => {
  const template = "Mobile Legends — пополнение в Узбекистане | yupay";
  expect(brandPageTitle(null, template)).toBe(template);
  expect(brandPageTitle(undefined, template)).toBe(template);
  expect(brandPageTitle("   ", template)).toBe(template);
});

it("prefers the brand's own description, else the fallback", () => {
  expect(brandPageDescription("Алмазы млбб за сумы.", "Общее")).toBe("Алмазы млбб за сумы.");
  expect(brandPageDescription(null, "Общее")).toBe("Общее");
  expect(brandPageDescription("  ", "Общее")).toBe("Общее");
});
