import { expect, it } from "vitest";

import { brandPageDescription, brandPageTitle, brandReviewsLd } from "./brand-seo";

import type { Review } from "./reviews";

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

const review = (over: Partial<Review>): Review => ({
  id: "r1",
  rating: 5,
  body: "Пришло за минуту",
  author_name: "Азиз",
  created_at: "2026-09-20T10:00:00Z",
  ...over,
});

it("marks up written reviews as schema.org Review", () => {
  expect(brandReviewsLd([review({})], "Покупатель")).toEqual([
    {
      "@type": "Review",
      author: { "@type": "Person", name: "Азиз" },
      reviewRating: { "@type": "Rating", ratingValue: 5, bestRating: 5 },
      reviewBody: "Пришло за минуту",
      datePublished: "2026-09-20",
    },
  ]);
});

it("skips star-only reviews, names guests, and caps the list", () => {
  const items = [
    review({ id: "a", body: null }),
    review({ id: "b", body: "  " }),
    review({ id: "c", author_name: null }),
    ...Array.from({ length: 9 }, (_, i) => review({ id: `x${String(i)}` })),
  ];
  const out = brandReviewsLd(items, "Покупатель");
  expect(out).toHaveLength(5);
  expect(out[0]?.author.name).toBe("Покупатель");
});
