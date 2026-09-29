// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { FeaturedReview } from "@/lib/reviews";

vi.mock("next-intl/server", () => ({ getTranslations: vi.fn() }));
vi.mock("@/lib/reviews", () => ({ getFeaturedReviews: vi.fn() }));

const { ReviewCard, avatarTint } = await import("./TrustReviews");

const REVIEW: FeaturedReview = {
  id: "r1",
  rating: 4,
  body: "Алмазы пришли за пару минут",
  author_name: "Aziz",
  author_photo_url: null,
  created_at: "2026-09-29T10:00:00Z",
  brand_slug: "mobile-legends",
  brand_name: "Mobile Legends",
  brand_logo_url: "https://cdn.yupay.uz/mlbb.webp",
};

it("shows who wrote it, their stars, the text and what they bought", () => {
  render(<ReviewCard review={REVIEW} anonymous="Покупатель" starsLabel="Оценка 4 из 5" />);
  expect(screen.getByText("Aziz")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Оценка 4 из 5" })).toBeInTheDocument();
  expect(screen.getByText("«Алмазы пришли за пару минут»")).toBeInTheDocument();
  expect(screen.getByText("Mobile Legends")).toBeInTheDocument();
  expect(screen.getByText("A")).toBeInTheDocument(); // no photo: the initial
});

it("names an anonymous reviewer generically", () => {
  render(
    <ReviewCard
      review={{ ...REVIEW, author_name: null }}
      anonymous="Покупатель"
      starsLabel="Оценка 4 из 5"
    />,
  );
  expect(screen.getByText("Покупатель")).toBeInTheDocument();
});

it("keeps a reviewer's avatar colour stable", () => {
  expect(avatarTint("Aziz")).toBe(avatarTint("Aziz"));
});
