// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { WriteReviewPanel } from "./WriteReviewPanel";

import type { Me } from "@/lib/auth";
import type { ReactNode } from "react";

vi.mock("next-intl", () => ({
  useTranslations: (ns: string) => (k: string) => `${ns}.${k}`,
}));

let mockSearch = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => mockSearch,
}));

let mockUser: Pick<Me, "id"> | null = { id: "user-1" };
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: mockUser }),
}));

vi.mock("@/lib/reviews", () => ({
  submitReview: vi.fn(),
}));

function wrap(ui: ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  mockSearch = new URLSearchParams();
  mockUser = { id: "user-1" };
});

test("scrolls the reviews section into view when the visitor came to rate an order", async () => {
  mockSearch = new URLSearchParams("order=order-1");
  const scrollIntoView = vi.fn();
  const section = document.createElement("section");
  section.id = "reviews";
  section.scrollIntoView = scrollIntoView;
  document.body.appendChild(section);

  wrap(<WriteReviewPanel brandSlug="steam" />);

  expect(screen.getByText("web.brandReviews.askTitle")).toBeInTheDocument();
  await waitFor(() => {
    expect(scrollIntoView).toHaveBeenCalled();
  });
  section.remove();
});

test("renders nothing and scrolls nowhere without an order in the URL", () => {
  const scrollIntoView = vi.fn();
  const section = document.createElement("section");
  section.id = "reviews";
  section.scrollIntoView = scrollIntoView;
  document.body.appendChild(section);

  const { container } = wrap(<WriteReviewPanel brandSlug="steam" />);

  expect(container).toBeEmptyDOMElement();
  expect(scrollIntoView).not.toHaveBeenCalled();
  section.remove();
});
